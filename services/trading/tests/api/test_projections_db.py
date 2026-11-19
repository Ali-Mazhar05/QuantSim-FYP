"""The projection, state, verify, rebuild and metrics routes on a real trading_db, after
the worker has run a portfolio on the A14 fixture: every route serves exactly what the
projection tables hold, the state at the last seq is the state row, the rebuild is
identical with the run's final hash, and the metrics' trades and costs are the sums over
the fills (A-FR-11, A-FR-14, A-FR-15)."""

import shutil
import sys
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
from api_support import (
    API,
    ENV_ID,
    FIXTURE,
    MOMENTUM,
    as_role,
    client_for,
    db_app,
    make_settings,
    portfolio_body,
)
from sqlalchemy import func, select

from qs_template import Database
from qs_template.auth import Role
from qs_template.jobs import Worker
from qs_trading.adapters.file_environment import file_environments
from qs_trading.jobs import ENGINE_RUN, build_handlers, job_queue
from qs_trading.models import (
    fill,
    holding_history,
    job,
    portfolio_state_current,
    portfolio_value,
)

# The database helpers live beside the other database tests
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "db"))
from trading_db_support import TradingDb, migrated_database, run

pytestmark = pytest.mark.db


def test_the_projection_routes_serve_the_projection_tables_after_a_run(tmp_path: Path) -> None:
    """On a database of its own, so the worker claims this test's job and no other."""
    shutil.copyfile(FIXTURE, tmp_path / f"{ENV_ID}.json")
    with migrated_database() as own:
        _run_and_read_the_projections(own, tmp_path)


async def _rows(database: Database, table: Any, portfolio_id: uuid.UUID, *order: Any) -> list[Any]:
    async with database.transaction() as session:
        result = await session.execute(
            select(table).where(table.c.portfolio_id == portfolio_id).order_by(*order)
        )
        return [dict(row._mapping) for row in result]


async def _paged(http: httpx.AsyncClient, url: str, headers: dict[str, str]) -> list[Any]:
    items: list[Any] = []
    after = 0
    while True:
        page = await http.get(url, params={"after_seq": after, "limit": 3}, headers=headers)
        assert page.status_code == 200, page.text
        body = page.json()
        items += body["items"]
        if body["next_cursor"] is None:
            return items
        after = body["next_cursor"]


def _run_and_read_the_projections(trading_db: TradingDb, tmp_path: Path) -> None:
    async def scenario(http: httpx.AsyncClient, database: Database) -> None:
        quant, viewer, admin = as_role(Role.QUANT), as_role(Role.VIEWER), as_role(Role.ADMIN)
        strategy_id = (await http.post(f"{API}/strategies", json=MOMENTUM, headers=quant)).json()[
            "id"
        ]
        created = await http.post(
            f"{API}/portfolios",
            json=portfolio_body(strategy_id, replay_environment_id=ENV_ID),
            headers=quant,
        )
        assert created.status_code == 201, created.text
        portfolio_id = uuid.UUID(created.json()["id"])
        base = f"{API}/portfolios/{portfolio_id}"

        submitted = await http.post(f"{base}/runs", headers=quant)
        assert submitted.status_code == 202, submitted.text
        job_id = submitted.json()["job_id"]
        settings = make_settings(trading_db.app_url)
        handlers = build_handlers(database, file_environments(tmp_path))
        worker = Worker(database, job_queue(settings), {ENGINE_RUN: handlers[ENGINE_RUN]})
        async with database.transaction() as session:
            assert await session.scalar(select(func.count()).select_from(job)) == 1
        assert await worker.run_once()
        done = (await http.get(f"{base}/runs/{job_id}", headers=viewer)).json()
        assert done["status"] == "succeeded", done["error"]

        # Fills, holding history and value series are the tables, row for row
        fills = await _rows(database, fill, portfolio_id, fill.c.seq)
        assert fills
        served_fills = await _paged(http, f"{base}/fills", viewer)
        assert [f["seq"] for f in served_fills] == [row["seq"] for row in fills]
        for served, row in zip(served_fills, fills, strict=True):
            for name, value in served.items():
                expected = row[name]
                assert (Decimal(value) if isinstance(expected, Decimal) else value) == expected

        holdings = await _rows(
            database, holding_history, portfolio_id, holding_history.c.seq, holding_history.c.symbol
        )
        served_history = await _paged(http, f"{base}/holdings/history", viewer)
        assert [(h["seq"], h["symbol"], h["quantity"]) for h in served_history] == [
            (row["seq"], row["symbol"], row["quantity"]) for row in holdings
        ]
        assert [Decimal(h["cost_basis"]) for h in served_history] == [
            row["cost_basis"] for row in holdings
        ]

        values = await _rows(database, portfolio_value, portfolio_id, portfolio_value.c.session)
        series = (await http.get(f"{base}/value-series", headers=viewer)).json()
        assert [p["session"] for p in series] == [row["session"] for row in values]
        assert len(series) == 10
        assert [Decimal(p["value"]) for p in series] == [row["value"] for row in values]
        assert [p["seq"] for p in series] == [row["seq"] for row in values]

        # Holdings and the state at the last seq are the state row
        (state,) = await _rows(database, portfolio_state_current, portfolio_id)
        positions = {
            symbol: (int(item["quantity"]), Decimal(str(item["cost_basis"])))
            for symbol, item in state["positions"].items()
        }
        held = (await http.get(f"{base}/holdings", headers=viewer)).json()
        assert held["last_seq"] == state["last_seq"]
        assert held["last_session"] == state["last_session"]
        assert Decimal(held["cash"]) == state["cash"]
        assert {
            p["symbol"]: (p["quantity"], Decimal(p["cost_basis"])) for p in held["positions"]
        } == positions

        at_last = await http.get(
            f"{base}/state", params={"as_of_seq": state["last_seq"]}, headers=viewer
        )
        assert at_last.status_code == 200, at_last.text
        snapshot = at_last.json()
        assert snapshot["seq"] == state["last_seq"] and snapshot["hash"] == state["last_hash"]
        assert snapshot["session"] == state["last_session"]
        assert Decimal(snapshot["cash"]) == state["cash"]
        assert {
            p["symbol"]: (p["quantity"], Decimal(p["cost_basis"])) for p in snapshot["positions"]
        } == positions
        assert Decimal(snapshot["last_value"]) == values[-1]["value"]
        beyond = await http.get(
            f"{base}/state", params={"as_of_seq": state["last_seq"] + 1}, headers=viewer
        )
        assert beyond.status_code == 404

        # The log verifies and rebuilds identical, ending at the run's final hash
        report = (await http.get(f"{base}/verify", headers=viewer)).json()
        assert report["valid"] is True and report["last_seq"] == state["last_seq"]
        assert report["last_hash"] == done["result"]["final_hash"]
        assert (await http.post(f"{base}/rebuild", headers=quant)).status_code == 403
        rebuilt = await http.post(f"{base}/rebuild", params={"apply": "true"}, headers=admin)
        assert rebuilt.status_code == 200, rebuilt.text
        assert rebuilt.json()["status"] == "identical"
        assert rebuilt.json()["applied"] is False and rebuilt.json()["differences"] == []
        assert rebuilt.json()["final_seq"] == state["last_seq"]
        assert rebuilt.json()["final_hash"] == done["result"]["final_hash"]

        # Metrics: trades and costs are the sums over the fills
        metrics = (await http.get(f"{base}/metrics", headers=viewer)).json()
        assert metrics["trades"] == len(fills)
        assert Decimal(metrics["total_costs"]) == sum(row["cost_total"] for row in fills)
        assert metrics["sessions"] == len(values)
        assert Decimal(metrics["final_value"]) == values[-1]["value"]
        assert metrics["final_hash"] == done["result"]["final_hash"]
        assert metrics["pending"] == [
            "total_return",
            "volatility",
            "sharpe",
            "max_drawdown",
            "turnover",
        ]

    async def main() -> None:
        settings = make_settings(trading_db.app_url)
        database = Database(settings)
        try:
            async with client_for(db_app(database, settings)) as http:
                await scenario(http, database)
        finally:
            await database.close()

    run(main())
