"""The market audit feed: instrument and environment changes and ingestion runs, in the
Audit Log page's row shape. The audit log is append-only, so these tests use their own
symbols and look for their own rows."""

import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy import text

from qs_template import Database
from qs_template.auth import Role
from tests import instrument_support as support
from tests.instrument_support import API, NEW_INSTRUMENT, bearer, make_token

client = support.client
database = support.database
pytestmark = pytest.mark.db


async def insert_run(
    database: Database,
    *,
    status: str,
    instrument_id: str,
    received: int,
    rejected: int,
    requested_by: str = "scheduler",
    error: str | None = None,
) -> str:
    async with database.transaction() as session:
        run_id = (
            await session.execute(
                text(
                    "INSERT INTO ingestion_run (mode, status, vendor, requested_by, error,"
                    " created_at, started_at, finished_at) VALUES ('manual', :status, 'fixture',"
                    " :by, :error, now() - interval '2 minutes', now() - interval '1 minute',"
                    " now()) RETURNING id"
                ),
                {"status": status, "by": requested_by, "error": error},
            )
        ).scalar_one()
        await session.execute(
            text(
                "INSERT INTO ingestion_run_item (run_id, instrument_id, status, received,"
                " passed_untouched, rejected, new_bars) VALUES (:run, :i, :s, :r, :p, :x, :p)"
            ),
            {
                "run": run_id,
                "i": instrument_id,
                "s": "failed" if status == "failed" else "succeeded",
                "r": received,
                "p": received - rejected,
                "x": rejected,
            },
        )
    return str(run_id)


def find(feed: list[dict[str, Any]], action: str) -> dict[str, Any]:
    matches = [event for event in feed if event["action"] == action]
    assert matches, f"{action!r} not in {[e['action'] for e in feed]}"
    return matches[0]


async def test_instrument_and_environment_changes_name_the_actor(
    client: httpx.AsyncClient,
) -> None:
    admin_id = uuid.uuid4()
    admin = bearer(make_token(Role.ADMIN, user_id=admin_id))
    symbol = f"AUD{uuid.uuid4().hex[:4].upper()}"
    created = await client.post(
        f"{API}/instruments", json={**NEW_INSTRUMENT, "symbol": symbol}, headers=admin
    )
    instrument_id = created.json()["id"]
    await client.patch(
        f"{API}/instruments/{instrument_id}", json={"sector": "Chips"}, headers=admin
    )
    await client.post(f"{API}/instruments/{instrument_id}/retire", headers=admin)
    env_name = f"Audit env {symbol}"
    other = await client.post(
        f"{API}/instruments", json={**NEW_INSTRUMENT, "symbol": f"{symbol}X"}, headers=admin
    )
    await client.post(
        f"{API}/environments",
        json={
            "name": env_name,
            "type": "synthetic",
            "universe": "Audit basket",
            "instrument_ids": [other.json()["id"]],
            "start_date": "2024-01-02",
            "end_date": "2024-06-28",
        },
        headers=admin,
    )

    response = await client.get(f"{API}/audit", headers=admin)
    assert response.status_code == 200, response.text
    feed = response.json()
    times = [event["occurred_at"] for event in feed]
    assert times == sorted(times, reverse=True)
    assert len({event["id"] for event in feed}) == len(feed)

    added = find(feed, f"Instrument {symbol} added")
    assert added["actor_id"] == str(admin_id)
    assert added["service"] == "Market Data"
    assert added["severity"] == "info"
    updated = find(feed, f"Instrument {symbol} updated")
    assert "sector: Technology → Chips" in updated["detail"]
    assert find(feed, f"Instrument {symbol} retired")["severity"] == "warning"
    env = find(feed, f"Market environment {env_name} created")
    assert env["actor_id"] == str(admin_id)
    assert "Synthetic Market, 1 instruments, 2024-01-02 → 2024-06-28" in env["detail"]


async def test_runs_report_their_outcome_and_severity(
    client: httpx.AsyncClient, database: Database
) -> None:
    admin = bearer(make_token(Role.ADMIN))
    created = await client.post(
        f"{API}/instruments", json={**NEW_INSTRUMENT, "symbol": "RUNAUD"}, headers=admin
    )
    instrument_id = created.json()["id"]
    user = str(uuid.uuid4())
    clean = await insert_run(
        database, status="succeeded", instrument_id=instrument_id, received=40, rejected=0
    )
    dirty = await insert_run(
        database,
        status="succeeded",
        instrument_id=instrument_id,
        received=40,
        rejected=3,
        requested_by=user,
    )
    failed = await insert_run(
        database,
        status="failed",
        instrument_id=instrument_id,
        received=0,
        rejected=0,
        error="vendor unavailable",
    )

    feed = (await client.get(f"{API}/audit", headers=admin)).json()
    by_id = {event["id"]: event for event in feed}

    assert by_id[f"market:run:{clean}:finished"]["severity"] == "info"
    assert "40 bars received, 40 passed" in by_id[f"market:run:{clean}:finished"]["detail"]
    assert by_id[f"market:run:{clean}:requested"]["actor_id"] is None  # the scheduler
    rejected = by_id[f"market:run:{dirty}:finished"]
    assert rejected["severity"] == "warning"
    assert "3 rejected" in rejected["detail"]
    assert by_id[f"market:run:{dirty}:requested"]["actor_id"] == user
    broken = by_id[f"market:run:{failed}:finished"]
    assert broken["severity"] == "critical"
    assert broken["action"] == "Ingestion run failed"
    assert "vendor unavailable" in broken["detail"]


async def test_feed_is_admin_only_and_honours_the_limit(client: httpx.AsyncClient) -> None:
    admin = bearer(make_token(Role.ADMIN))
    for n in range(3):
        await client.post(
            f"{API}/instruments", json={**NEW_INSTRUMENT, "symbol": f"LIM{n}"}, headers=admin
        )
    assert len((await client.get(f"{API}/audit?limit=2", headers=admin)).json()) == 2
    assert (await client.get(f"{API}/audit?limit=0", headers=admin)).status_code == 422
    quant = bearer(make_token(Role.QUANT))
    assert (await client.get(f"{API}/audit", headers=quant)).status_code == 403
