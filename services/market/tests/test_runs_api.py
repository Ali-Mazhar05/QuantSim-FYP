"""The ingestion run routes against a real database, signed tokens for every role and
the recorded fixture vendor. The chain test posts a run, executes it with the real runner
and reads the report back through the API."""

import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import insert, select, text

from qs_market.models import bar, ingestion_run, instrument
from qs_market.pipeline.runner import PipelineConfig, run_next
from qs_market.vendor.fixture import FixtureSource
from qs_template import Database
from qs_template.auth import Role
from tests import instrument_support as support
from tests.instrument_support import API, bearer, make_token

client = support.client
pytestmark = pytest.mark.db

RUNS = f"{API}/ingestion-runs"
FIXTURES = Path(__file__).parent / "fixtures"
AS_OF = datetime(2025, 1, 6, 12, 0, tzinfo=UTC)
AAPL_WINDOW = {"start": "2024-01-02", "end": "2024-02-13"}
NVDA_WINDOW = {"start": "2024-05-28", "end": "2024-06-21"}
CONFIG = PipelineConfig(backfill_start=date(2024, 1, 2))


@pytest.fixture
async def database(
    migrated_database_url: str,
) -> AsyncIterator[Database]:
    """The support database, with the run queue emptied as well (the support fixture only
    clears the instruments)."""
    db = Database(support.make_settings(migrated_database_url))
    async with db.transaction() as session:
        await session.execute(text("TRUNCATE ingestion_run, instrument, outbox CASCADE"))
    try:
        yield db
    finally:
        async with db.transaction() as session:
            await session.execute(text("TRUNCATE ingestion_run, instrument, outbox CASCADE"))
        await db.close()


def admin() -> dict[str, str]:
    return bearer(make_token(Role.ADMIN))


async def add_instrument(db: Database, symbol: str) -> uuid.UUID:
    async with db.transaction() as session:
        return (
            await session.execute(
                insert(instrument)
                .values(
                    symbol=symbol,
                    name=symbol,
                    sector="Technology",
                    exchange="XNAS",
                    calendar="XNYS",
                    currency="USD",
                    asset_class="equity",
                    vendor_symbol=symbol,
                )
                .returning(instrument.c.id)
            )
        ).scalar_one()


def fixture_sessions(symbol: str, start: str, end: str) -> int:
    """Sessions the recorded file holds inside a window, counted from the file itself."""
    records = json.loads((FIXTURES / f"{symbol}.json").read_text(encoding="utf-8"))
    return sum(1 for r in records if start <= r["date"][:10] <= end)


class Damaged:
    """The recorded vendor with three bars broken, so the gate must reject them."""

    name = "fixture"

    def __init__(self) -> None:
        self._inner = FixtureSource(FIXTURES)

    async def fetch_daily(self, symbol: str, start: date, end: date) -> list[dict[str, Any]]:
        rows = [dict(r) for r in await self._inner.fetch_daily(symbol, start, end)]
        rows[5]["low"] = rows[5]["high"] + 1
        rows[6]["volume"] = -1
        rows[7]["open"] = 0
        return rows


async def execute(db: Database, source: Any = None) -> None:
    outcome = await run_next(db, lambda run: source or FixtureSource(FIXTURES), CONFIG, as_of=AS_OF)
    assert outcome is not None


@pytest.mark.parametrize(
    ("role", "allowed"),
    [(Role.ADMIN, True), (Role.QUANT, False), (Role.ANALYST, False), (Role.VIEWER, False)],
)
async def test_only_an_admin_enqueues(client: httpx.AsyncClient, role: Role, allowed: bool) -> None:
    response = await client.post(
        RUNS, json={"mode": "manual", **AAPL_WINDOW}, headers=bearer(make_token(role))
    )
    assert response.status_code == (202 if allowed else 403)


async def test_enqueue_needs_a_valid_token(client: httpx.AsyncClient) -> None:
    body = {"mode": "manual"}
    assert (await client.post(RUNS, json=body)).status_code == 401
    forged = bearer(make_token(Role.ADMIN, forged=True))
    assert (await client.post(RUNS, json=body, headers=forged)).status_code == 401


@pytest.mark.parametrize(
    ("role", "allowed"),
    [(Role.ADMIN, True), (Role.QUANT, True), (Role.ANALYST, True), (Role.VIEWER, False)],
)
async def test_history_is_for_admin_quant_and_analyst(
    client: httpx.AsyncClient, role: Role, allowed: bool
) -> None:
    headers = bearer(make_token(role))
    missing = uuid.uuid4()
    assert (await client.get(RUNS, headers=headers)).status_code == (200 if allowed else 403)
    detail = await client.get(f"{RUNS}/{missing}", headers=headers)
    assert detail.status_code == (404 if allowed else 403)
    rejected = await client.get(f"{RUNS}/{missing}/rejected", headers=headers)
    assert rejected.status_code == (404 if allowed else 403)
    assert (await client.get(RUNS)).status_code == 401


async def test_accepted_run_is_pending_and_names_the_actor_and_vendor(
    client: httpx.AsyncClient, database: Database
) -> None:
    aapl = await add_instrument(database, "AAPL")
    actor = uuid.uuid4()
    response = await client.post(
        RUNS,
        json={"mode": "backfill", "instrument_ids": [str(aapl)], **AAPL_WINDOW},
        headers=bearer(make_token(Role.ADMIN, user_id=actor)),
    )
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "pending" and body["created"] is True
    detail = (await client.get(f"{RUNS}/{body['id']}", headers=admin())).json()
    assert detail["mode"] == "backfill"
    assert detail["requested_by"] == str(actor)
    assert detail["vendor"] == "fixture"
    assert detail["instrument_ids"] == [str(aapl)]
    assert (detail["window_start"], detail["window_end"]) == ("2024-01-02", "2024-02-13")
    assert detail["items"] == [] and detail["report"] is None


async def test_conflict_names_the_active_run(client: httpx.AsyncClient, database: Database) -> None:
    aapl = await add_instrument(database, "AAPL")
    nvda = await add_instrument(database, "NVDA")

    def body(instrument_id: uuid.UUID, window: dict[str, str]) -> dict[str, Any]:
        return {"mode": "manual", "instrument_ids": [str(instrument_id)], **window}

    first = await client.post(RUNS, json=body(aapl, AAPL_WINDOW), headers=admin())
    clash = await client.post(RUNS, json=body(aapl, AAPL_WINDOW), headers=admin())
    assert clash.status_code == 409
    assert clash.headers["content-type"].startswith("application/problem+json")
    assert clash.json()["active_run_id"] == first.json()["id"]
    assert first.json()["id"] in clash.json()["detail"]
    # A different instrument, or a different window, is no conflict
    other = await client.post(RUNS, json=body(nvda, AAPL_WINDOW), headers=admin())
    assert other.status_code == 202
    later = await client.post(RUNS, json=body(aapl, NVDA_WINDOW), headers=admin())
    assert later.status_code == 202


async def test_idempotency_key_returns_the_same_run(
    client: httpx.AsyncClient, database: Database
) -> None:
    body = {"mode": "manual", "idempotency_key": "ui-click-1", **AAPL_WINDOW}
    first = await client.post(RUNS, json=body, headers=admin())
    second = await client.post(RUNS, json=body, headers=admin())
    assert second.status_code == 202
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["created"] is False
    async with database.transaction() as session:
        rows = (await session.execute(select(ingestion_run.c.id))).all()
    assert len(rows) == 1


@pytest.mark.parametrize(
    "body",
    [
        {"mode": "manual", "start": "2024-02-13", "end": "2024-01-02"},
        {"mode": "backfill", "end": "2024-02-13"},
        {"mode": "daily"},
        {"mode": "manual", "instrument_ids": []},
        {"mode": "manual", "surprise": 1},
    ],
)
async def test_bad_bodies_are_422_problem_details(
    client: httpx.AsyncClient, body: dict[str, Any]
) -> None:
    response = await client.post(RUNS, json=body, headers=admin())
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")


async def test_unknown_instrument_ids_are_422_and_create_nothing(
    client: httpx.AsyncClient, database: Database
) -> None:
    aapl = await add_instrument(database, "AAPL")
    ghost = uuid.uuid4()
    response = await client.post(
        RUNS,
        json={"mode": "manual", "instrument_ids": [str(aapl), str(ghost)]},
        headers=admin(),
    )
    assert response.status_code == 422
    assert response.json()["unknown_instrument_ids"] == [str(ghost)]
    async with database.transaction() as session:
        assert (await session.execute(select(ingestion_run.c.id))).first() is None


async def test_list_is_newest_first_filtered_and_limited(
    client: httpx.AsyncClient, database: Database
) -> None:
    ids = []
    for day in range(1, 4):
        response = await client.post(
            RUNS,
            json={"mode": "manual", "start": f"2024-01-0{day}", "end": f"2024-01-0{day}"},
            headers=admin(),
        )
        ids.append(response.json()["id"])
    async with database.transaction() as session:
        await session.execute(
            text("UPDATE ingestion_run SET status = 'failed', error = 'x' WHERE id = :i"),
            {"i": ids[0]},
        )
    listed = (await client.get(RUNS, headers=admin())).json()
    assert [r["id"] for r in listed] == list(reversed(ids))
    failed = (await client.get(f"{RUNS}?status=failed", headers=admin())).json()
    assert [r["id"] for r in failed] == [ids[0]]
    assert len((await client.get(f"{RUNS}?limit=2", headers=admin())).json()) == 2
    for bad in ("limit=0", "limit=201", "status=bogus"):
        assert (await client.get(f"{RUNS}?{bad}", headers=admin())).status_code == 422


async def test_post_run_execute_get_report_matches(
    client: httpx.AsyncClient, database: Database
) -> None:
    aapl = await add_instrument(database, "AAPL")
    nvda = await add_instrument(database, "NVDA")
    # One window that covers both recorded files
    posted = await client.post(
        RUNS,
        json={"mode": "manual", "start": "2024-01-02", "end": "2024-06-21"},
        headers=admin(),
    )
    assert posted.status_code == 202
    run_id = posted.json()["id"]
    await execute(database)

    detail = (await client.get(f"{RUNS}/{run_id}", headers=admin())).json()
    assert detail["status"] == "succeeded", detail["error"]
    expected = {
        "AAPL": fixture_sessions("AAPL", "2024-01-02", "2024-06-21"),
        "NVDA": fixture_sessions("NVDA", "2024-01-02", "2024-06-21"),
    }
    assert expected == {"AAPL": 30, "NVDA": 18}
    items = {i["symbol"]: i for i in detail["items"]}
    assert set(items) == set(expected)
    for symbol, count in expected.items():
        item = items[symbol]
        assert item["status"] == "succeeded"
        assert item["received"] == item["passed_untouched"] == item["new_bars"] == count
        assert item["rejected"] == item["corrected"] == item["duplicates_removed"] == 0
    report = detail["report"]
    assert report["new_bars"] == report["received"] == sum(expected.values())
    assert report["rejected"] == 0
    assert report["instruments"] == {"succeeded": 2}
    assert detail["started_at"] and detail["finished_at"]
    assert detail["ruleset_version"] == report["ruleset_version"]

    async with database.transaction() as session:
        stored = {
            r.instrument_id: r.n
            for r in (
                await session.execute(
                    text("SELECT instrument_id, count(*) AS n FROM bar GROUP BY instrument_id")
                )
            ).all()
        }
    assert stored == {aapl: 30, nvda: 18}
    assert report["new_bars"] == sum(stored.values())


async def test_rejected_bars_are_listed_with_rules_and_payload_and_paginated(
    client: httpx.AsyncClient, database: Database
) -> None:
    await add_instrument(database, "AAPL")
    posted = await client.post(RUNS, json={"mode": "manual", **AAPL_WINDOW}, headers=admin())
    run_id = posted.json()["id"]
    await execute(database, Damaged())

    detail = (await client.get(f"{RUNS}/{run_id}", headers=admin())).json()
    assert detail["report"]["rejected"] == 3
    assert detail["items"][0]["rejected"] == 3
    # The bars that passed are stored, the rejected ones are not
    async with database.transaction() as session:
        assert len((await session.execute(select(bar.c.session_date))).all()) == 27

    page = (await client.get(f"{RUNS}/{run_id}/rejected", headers=admin())).json()
    assert page["total"] == 3 and len(page["items"]) == 3
    by_rule = {tuple(i["rules"]): i for i in page["items"]}
    assert set(by_rule) == {("ohlc_order",), ("negative_volume",), ("non_positive_price",)}
    for item in page["items"]:
        assert item["symbol"] == "AAPL"
        assert item["session_date"]
        assert item["payload"]
    assert str(by_rule[("negative_volume",)]["payload"]["volume"]) == "-1"

    first = (await client.get(f"{RUNS}/{run_id}/rejected?limit=2", headers=admin())).json()
    rest = (await client.get(f"{RUNS}/{run_id}/rejected?limit=2&offset=2", headers=admin())).json()
    assert len(first["items"]) == 2 and len(rest["items"]) == 1
    assert first["total"] == rest["total"] == 3
    ids = [i["id"] for i in first["items"] + rest["items"]]
    assert len(set(ids)) == 3
    over = await client.get(f"{RUNS}/{run_id}/rejected?limit=501", headers=admin())
    assert over.status_code == 422
