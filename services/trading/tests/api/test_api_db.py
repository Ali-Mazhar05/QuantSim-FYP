"""The Trading API against a real trading_db, wired exactly as deployed: strategies and
portfolios save and reload, bad bodies and bindings are refused, the role matrix holds,
and a submitted run executes on the worker and its log pages gap-free with a correct
cursor (A14 fixture)."""

import shutil
import sys
import uuid
from collections.abc import Awaitable, Callable, Iterator
from itertools import pairwise
from pathlib import Path
from typing import Any

import httpx
import pytest
from api_support import (
    API,
    MOMENTUM,
    as_role,
    check_role_matrix,
    client_for,
    db_app,
    error_locations,
    make_settings,
    portfolio_body,
    seed_targets,
)
from sqlalchemy import func, select

from qs_template import Database
from qs_template.auth import Role
from qs_template.jobs import Worker
from qs_trading.adapters.file_environment import file_environments
from qs_trading.jobs import ENGINE_RUN, build_handlers, job_queue
from qs_trading.models import job, portfolio, portfolio_state_current, strategy

# The database helpers live beside the other database tests
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "db"))
from trading_db_support import TradingDb, migrated_database, run

pytestmark = pytest.mark.db

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/environments/two_symbols_10_sessions.json"
ENV_ID = "5d0c6c1e-7a14-4a14-8a14-000000000001"

Scenario = Callable[[httpx.AsyncClient, Database], Awaitable[None]]


@pytest.fixture(scope="module")
def trading_db() -> Iterator[TradingDb]:
    with migrated_database() as database:
        yield database


def serve(trading_db: TradingDb, scenario: Scenario) -> None:
    """Run ``scenario`` against the deployed app on the test database."""

    async def main() -> None:
        settings = make_settings(trading_db.app_url)
        database = Database(settings)
        try:
            async with client_for(db_app(database, settings)) as http:
                await scenario(http, database)
        finally:
            await database.close()

    run(main())


async def _count(database: Database, table: Any, **where: Any) -> int:
    async with database.transaction() as session:
        query = select(func.count()).select_from(table)
        for name, value in where.items():
            query = query.where(table.c[name] == value)
        return int(await session.scalar(query) or 0)


def test_strategies_save_reload_list_and_edit(trading_db: TradingDb) -> None:
    async def scenario(http: httpx.AsyncClient, database: Database) -> None:
        quant, viewer = as_role(Role.QUANT), as_role(Role.VIEWER)
        bodies = [
            {"name": "Hold", "kind": "buy_and_hold", "params": {}},
            {"name": "Cross", "kind": "ma_crossover", "params": {"fast": 5, "slow": 20}},
            MOMENTUM,
            {"name": "Revert", "kind": "mean_reversion", "params": {"entry_z": "1.5"}},
        ]
        saved = []
        for body in bodies:
            created = await http.post(f"{API}/strategies", json=body, headers=quant)
            assert created.status_code == 201, created.text
            saved.append(created.json())
            reloaded = await http.get(f"{API}/strategies/{saved[-1]['id']}", headers=viewer)
            assert reloaded.json() == saved[-1]
            for name, value in body["params"].items():
                assert reloaded.json()["params"][name] == value
        listed = [s["id"] for s in (await http.get(f"{API}/strategies", headers=viewer)).json()]
        ours = [s["id"] for s in saved]
        assert [i for i in listed if i in ours] == ours[::-1]

        edited = await http.put(
            f"{API}/strategies/{saved[0]['id']}",
            json={"name": "Hold edited", "kind": "momentum", "params": {"lookback": 5}},
            headers=quant,
        )
        assert edited.status_code == 200, edited.text
        assert edited.json()["params"]["lookback"] == 5
        assert edited.json()["created_at"] == saved[0]["created_at"]

        bad = await http.post(
            f"{API}/strategies",
            json={**MOMENTUM, "params": {"lookback": 0}},
            headers=quant,
        )
        assert ["body", "params", "lookback"] in error_locations(bad)
        unknown = await http.post(
            f"{API}/strategies", json={**MOMENTUM, "kind": "astrology"}, headers=quant
        )
        assert ["body", "kind"] in error_locations(unknown)
        assert await _count(database, strategy, kind="astrology") == 0

    serve(trading_db, scenario)


def test_portfolios_bind_to_exactly_one_environment(trading_db: TradingDb) -> None:
    async def scenario(http: httpx.AsyncClient, database: Database) -> None:
        quant, analyst = as_role(Role.QUANT), as_role(Role.ANALYST)
        strategy_id = (await http.post(f"{API}/strategies", json=MOMENTUM, headers=quant)).json()[
            "id"
        ]
        replay = await http.post(
            f"{API}/portfolios", json=portfolio_body(strategy_id), headers=quant
        )
        assert replay.status_code == 201, replay.text
        assert replay.json()["initial_capital"] == "10000.00"
        assert replay.json()["cost_model"] == {
            "fixed": "1.00",
            "per_share": "0.01",
            "pct": "0.0005",
        }
        simulation_body = portfolio_body(
            strategy_id,
            name="Simulated",
            replay_environment_id=None,
            simulation_run_id=str(uuid.uuid4()),
            path_index=3,
        )
        simulation = await http.post(f"{API}/portfolios", json=simulation_body, headers=quant)
        assert simulation.status_code == 201, simulation.text
        assert simulation.json()["env_type"] == "simulation"
        assert simulation.json()["path_index"] == 3

        for created in (replay.json(), simulation.json()):
            got = await http.get(f"{API}/portfolios/{created['id']}", headers=analyst)
            assert got.json() == created
        listed = [p["id"] for p in (await http.get(f"{API}/portfolios", headers=analyst)).json()]
        assert listed.index(simulation.json()["id"]) < listed.index(replay.json()["id"])

        before = await _count(database, portfolio)
        neither = portfolio_body(strategy_id, replay_environment_id=None)
        both = portfolio_body(strategy_id, simulation_run_id=str(uuid.uuid4()), path_index=0)
        for body in (neither, both):
            refused = await http.post(f"{API}/portfolios", json=body, headers=quant)
            assert {loc[-1] for loc in error_locations(refused)} == {
                "replay_environment_id",
                "simulation_run_id",
            }
        stranger = portfolio_body(str(uuid.uuid4()))
        unknown = await http.post(f"{API}/portfolios", json=stranger, headers=quant)
        assert ["body", "strategy_id"] in error_locations(unknown)
        assert await _count(database, portfolio) == before

    serve(trading_db, scenario)


def test_every_route_allows_exactly_the_declared_roles(trading_db: TradingDb) -> None:
    async def scenario(http: httpx.AsyncClient, database: Database) -> None:
        await check_role_matrix(http, await seed_targets(http))

    serve(trading_db, scenario)


def test_a_run_submits_once_executes_and_its_log_pages_gap_free(tmp_path: Path) -> None:
    """On a database of its own: the worker claims the oldest queued job, and the other
    tests queue runs for environments no fixture serves."""
    shutil.copyfile(FIXTURE, tmp_path / f"{ENV_ID}.json")
    with migrated_database() as own:
        _run_and_page_the_log(own, tmp_path)


def _run_and_page_the_log(trading_db: TradingDb, tmp_path: Path) -> None:

    async def scenario(http: httpx.AsyncClient, database: Database) -> None:
        quant, viewer = as_role(Role.QUANT), as_role(Role.VIEWER)
        strategy_id = (await http.post(f"{API}/strategies", json=MOMENTUM, headers=quant)).json()[
            "id"
        ]
        created = await http.post(
            f"{API}/portfolios",
            json=portfolio_body(strategy_id, replay_environment_id=ENV_ID),
            headers=quant,
        )
        assert created.status_code == 201, created.text
        portfolio_id = created.json()["id"]
        base = f"{API}/portfolios/{portfolio_id}"

        keyed = {**quant, "Idempotency-Key": "submit-once"}
        first = await http.post(f"{base}/runs", headers=keyed)
        again = await http.post(f"{base}/runs", headers=keyed)
        assert first.status_code == again.status_code == 202, (first.text, again.text)
        job_id = first.json()["job_id"]
        assert again.json()["job_id"] == job_id
        assert first.json()["created"] is True and again.json()["created"] is False
        refused = await http.post(f"{base}/runs", headers=as_role(Role.ANALYST))
        assert refused.status_code == 403

        queued = (await http.get(f"{base}/runs/{job_id}", headers=viewer)).json()
        assert queued["status"] == "queued" and queued["progress"] == 0.0

        settings = make_settings(trading_db.app_url)
        handlers = build_handlers(database, file_environments(tmp_path))
        worker = Worker(database, job_queue(settings), {ENGINE_RUN: handlers[ENGINE_RUN]})
        async with database.transaction() as session:
            # Ours is the only job, so it is the one the worker claims
            assert await session.scalar(select(func.count()).select_from(job)) == 1
        assert await worker.run_once()

        done = (await http.get(f"{base}/runs/{job_id}", headers=viewer)).json()
        assert done["status"] == "succeeded", done["error"]
        assert done["progress"] == 1.0 and done["error"] is None
        assert done["finished_at"] is not None

        seqs: list[int] = []
        items: list[dict[str, Any]] = []
        after, limit = 0, 7
        while True:
            page = await http.get(
                f"{base}/events", params={"after_seq": after, "limit": limit}, headers=viewer
            )
            assert page.status_code == 200, page.text
            body = page.json()
            assert len(body["items"]) <= limit
            items += body["items"]
            seqs += [e["seq"] for e in body["items"]]
            if body["next_cursor"] is None:
                break
            assert body["next_cursor"] == body["items"][-1]["seq"]
            assert len(body["items"]) == limit
            after = body["next_cursor"]

        async with database.transaction() as session:
            last_seq = await session.scalar(
                select(portfolio_state_current.c.last_seq).where(
                    portfolio_state_current.c.portfolio_id == uuid.UUID(portfolio_id)
                )
            )
        assert seqs == list(range(1, int(last_seq or 0) + 1)) and len(seqs) > limit
        assert items[0]["type"] == "RUN_STARTED" and items[0]["prev_hash"] is None
        assert items[-1]["type"] == "RUN_COMPLETED"
        for previous, current in pairwise(items):
            assert current["prev_hash"] == previous["hash"]
        assert done["result"]["final_hash"] == items[-1]["hash"]

        # The portfolio has a log now, so its strategy is frozen
        edit = await http.put(f"{API}/strategies/{strategy_id}", json=MOMENTUM, headers=quant)
        assert edit.status_code == 409, edit.text

    serve(trading_db, scenario)
