"""B12: the replay feed and activation on a real database (B-FR-01 to B-FR-04, B-NFR-02, B-NFR-05).

The data is the recorded AAPL responses and a scaled copy (PEER) over the same sessions, ingested
by the real pipeline. A test changes the stored data with raw SQL, the way a vendor restatement or a
correction would, and checks what the feed and the fingerprint do (ADR 01, ADR 08)."""

import time
import uuid
from datetime import date, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from qs_market import feeds
from qs_market.api_data import MAX_LIMIT
from qs_market.environments import EnvironmentService
from qs_market.replay import ReplayService
from qs_template import Database
from qs_template.auth import Role
from tests import instrument_support as support
from tests import test_feed_contract_api as contract
from tests.contract_support import tick_problems
from tests.instrument_support import API, bearer, make_token
from tests.read_support import add_instrument
from tests.test_correlation_api import both_loaded

client = support.client
database = support.database
ready = contract.ready
instrument = contract.instrument
pytestmark = pytest.mark.db


def viewer() -> dict[str, str]:
    return bearer(make_token(Role.VIEWER))


async def read_all(
    http: httpx.AsyncClient, environment_id: str, *, limit: int = 7
) -> tuple[list[dict[str, Any]], set[str]]:
    """Every tick by following the cursor, and the fingerprints the pages named."""
    items: list[dict[str, Any]] = []
    fingerprints: set[str] = set()
    cursor = 0
    while True:
        response = await http.get(
            f"{API}/environments/{environment_id}/ticks",
            params={"after_seq": cursor, "limit": limit},
            headers=viewer(),
        )
        assert response.status_code == 200, response.text
        fingerprints.add(response.headers["X-Source-Fingerprint"])
        body = response.json()
        items += body["items"]
        if body["next_after_seq"] is None:
            return items, fingerprints
        cursor = body["next_after_seq"]


async def sql(database: Database, statement: str, **params: Any) -> None:
    async with database.transaction() as session:
        await session.execute(text(statement), params)


async def scalar(database: Database, statement: str, **params: Any) -> Any:
    async with database.transaction() as session:
        return (await session.execute(text(statement), params)).scalar_one()


async def activate(
    http: httpx.AsyncClient, environment_id: str, *, user: uuid.UUID | None = None
) -> httpx.Response:
    return await http.post(
        f"{API}/environments/{environment_id}/activate",
        headers=bearer(make_token(Role.QUANT, user_id=user)),
    )


# ---- the feed ----


async def test_the_feed_is_ordered_gap_free_and_follows_the_contract(
    client: httpx.AsyncClient, ready: dict[str, Any]
) -> None:
    items, fingerprints = await read_all(client, ready["id"])
    assert len(items) > 40
    assert [t["seq"] for t in items] == list(range(1, len(items) + 1))
    assert [(t["session"], t["symbol"]) for t in items] == sorted(
        (t["session"], t["symbol"]) for t in items
    )
    assert {t["symbol"] for t in items} == {"AAPL", "PEER"}
    assert sorted({t["session"] for t in items}) == list(range(len(items) // 2))
    assert {t["env_id"] for t in items} == {ready["id"]}
    assert all(t["env_type"] == "replay" and t["path_index"] is None for t in items)
    problems = {t["seq"]: tick_problems(t) for t in items if tick_problems(t)}
    assert problems == {}, list(problems.items())[:3]
    assert len(fingerprints) == 1
    assert {t["source_fingerprint"] for t in items} == fingerprints


async def test_two_reads_are_byte_identical(
    client: httpx.AsyncClient, ready: dict[str, Any]
) -> None:
    url = f"{API}/environments/{ready['id']}/ticks"
    first = await client.get(url, params={"limit": 25}, headers=viewer())
    second = await client.get(url, params={"limit": 25}, headers=viewer())
    assert first.status_code == 200 and first.content == second.content
    assert first.headers["X-Source-Fingerprint"] == second.headers["X-Source-Fingerprint"]


async def test_the_database_side_fingerprint_and_ticks_equal_the_pure_core(
    client: httpx.AsyncClient, database: Database, ready: dict[str, Any]
) -> None:
    # the feed has PostgreSQL write each bar's canonical line; the pure core writes it from values.
    # The two must agree byte for byte, or the fixtures (made by the pure core) would drift
    served, fingerprints = await read_all(client, ready["id"], limit=MAX_LIMIT)
    async with database.transaction() as session:
        environment = await EnvironmentService(session).get(uuid.UUID(ready["id"]))
        rows = await ReplayService(session).rows(environment)
    assert feeds.fingerprint(rows) == fingerprints.pop()
    expected = feeds.build_ticks(
        rows, env_id=uuid.UUID(ready["id"]), source_fingerprint=feeds.fingerprint(rows)
    )
    assert served == expected


async def test_paging_covers_every_tick_once_and_ends_cleanly(
    client: httpx.AsyncClient, ready: dict[str, Any]
) -> None:
    url = f"{API}/environments/{ready['id']}/ticks"
    everything, _ = await read_all(client, ready["id"], limit=MAX_LIMIT)
    total = len(everything)
    for limit in (1, 5, 13, total):
        items, _ = await read_all(client, ready["id"], limit=limit)
        assert items == everything, limit
    first = (await client.get(url, params={"limit": 5}, headers=viewer())).json()
    assert [t["seq"] for t in first["items"]] == [1, 2, 3, 4, 5] and first["next_after_seq"] == 5
    last = (
        await client.get(url, params={"after_seq": total - 2, "limit": 5}, headers=viewer())
    ).json()
    assert [t["seq"] for t in last["items"]] == [total - 1, total] and last[
        "next_after_seq"
    ] is None
    exact = (await client.get(url, params={"limit": total}, headers=viewer())).json()
    assert exact["next_after_seq"] is None, "exactly one full page is also the last"
    past = await client.get(url, params={"after_seq": total + 50}, headers=viewer())
    assert past.status_code == 200 and past.json() == {"items": [], "next_after_seq": None}
    assert past.headers["X-Source-Fingerprint"]


async def test_only_the_environments_instruments_and_window_are_served(
    client: httpx.AsyncClient, database: Database
) -> None:
    ids = await both_loaded(database)
    narrow = await contract.make_environment(
        client, ids["AAPL"], start="2024-01-10", end="2024-01-31"
    )
    items, _ = await read_all(client, narrow["id"])
    assert items and {t["symbol"] for t in items} == {"AAPL"}
    assert min(t["session_date"] for t in items) >= "2024-01-10"
    assert max(t["session_date"] for t in items) <= "2024-01-31"
    assert items[0]["session"] == 0, "session counts from the first session served"


async def test_an_absent_symbol_has_no_tick_and_seq_stays_gap_free(
    client: httpx.AsyncClient, database: Database, ready: dict[str, Any]
) -> None:
    before, _ = await read_all(client, ready["id"])
    victim = next(t for t in before if t["symbol"] == "PEER" and t["session"] == 3)
    await sql(
        database,
        "DELETE FROM bar WHERE instrument_id = :i AND session_date = :d",
        i=uuid.UUID(victim["instrument_id"]),
        d=date.fromisoformat(victim["session_date"]),
    )
    after, _ = await read_all(client, ready["id"])
    assert len(after) == len(before) - 1
    assert [t["seq"] for t in after] == list(range(1, len(after) + 1))
    assert [t["symbol"] for t in after if t["session"] == 3] == ["AAPL"]
    assert max(t["session"] for t in after) == max(t["session"] for t in before)
    response = await activate(client, ready["id"])
    assert response.json()["missing_session_count"] == 1


# ---- the fingerprint (ADR 08) ----


async def fingerprint(client: httpx.AsyncClient, environment_id: str) -> str:
    _, fingerprints = await read_all(client, environment_id, limit=MAX_LIMIT)
    assert len(fingerprints) == 1
    return fingerprints.pop()


async def test_a_bar_revision_changes_the_fingerprint_and_nothing_served(
    client: httpx.AsyncClient, database: Database, ready: dict[str, Any]
) -> None:
    before, fp = await read_all(client, ready["id"])
    target = before[4]
    await sql(
        database,
        "UPDATE bar SET revision = revision + 1 WHERE instrument_id = :i AND session_date = :d",
        i=uuid.UUID(target["instrument_id"]),
        d=date.fromisoformat(target["session_date"]),
    )
    after, fp_after = await read_all(client, ready["id"])
    assert fp_after != fp
    strip = [{k: v for k, v in t.items() if k != "source_fingerprint"} for t in before]
    assert strip == [{k: v for k, v in t.items() if k != "source_fingerprint"} for t in after]


async def test_a_restated_adjusted_price_changes_the_fingerprint_and_the_served_price(
    client: httpx.AsyncClient, database: Database, ready: dict[str, Any]
) -> None:
    # the vendor restates adjusted prices at every dividend, with no revision number (runner.py)
    before, fp = await read_all(client, ready["id"])
    target = before[4]
    await sql(
        database,
        "UPDATE bar SET adj_close = adj_close * 1.01"
        " WHERE instrument_id = :i AND session_date = :d",
        i=uuid.UUID(target["instrument_id"]),
        d=date.fromisoformat(target["session_date"]),
    )
    after, fp_after = await read_all(client, ready["id"])
    assert fp_after != fp
    changed = [
        (a["seq"], b["close"], a["close"])
        for a, b in zip(after, before, strict=True)
        if a["close"] != b["close"]
    ]
    assert [c[0] for c in changed] == [target["seq"]]
    assert float(changed[0][2]) == pytest.approx(float(changed[0][1]) * 1.01, rel=1e-9)


async def test_what_is_outside_the_environment_does_not_change_the_fingerprint(
    client: httpx.AsyncClient, database: Database, ready: dict[str, Any]
) -> None:
    before, fp = await read_all(client, ready["id"])
    stranger = await add_instrument(database, "OUTSIDER")
    async with database.transaction() as session:
        # another instrument, in the same window; and a bar of an environment instrument after it
        for offset in range(5):
            await support.insert_bar(
                session, stranger, date(2024, 1, 2) + timedelta(days=offset), "50"
            )
        await support.insert_bar(
            session, uuid.UUID(before[0]["instrument_id"]), date(2024, 3, 1), "99"
        )
    after, fp_after = await read_all(client, ready["id"])
    assert fp_after == fp and after == before


# ---- what cannot be served ----


async def test_a_bar_without_adjusted_prices_refuses_the_feed_and_activation(
    client: httpx.AsyncClient, database: Database, ready: dict[str, Any]
) -> None:
    items, _ = await read_all(client, ready["id"])
    victim = items[6]
    await sql(
        database,
        "UPDATE bar SET adj_close = NULL WHERE instrument_id = :i AND session_date = :d",
        i=uuid.UUID(victim["instrument_id"]),
        d=date.fromisoformat(victim["session_date"]),
    )
    served = await client.get(f"{API}/environments/{ready['id']}/ticks", headers=viewer())
    assert served.status_code == 422
    body = served.json()
    assert body["type"] == "urn:quantsim:problem:missing-adjusted-prices"
    assert body["missing"] == {victim["symbol"]: 1}
    refused = await activate(client, ready["id"])
    assert refused.status_code == 422 and refused.json()["missing"] == {victim["symbol"]: 1}
    assert (
        await scalar(
            database,
            "SELECT status FROM market_environment WHERE id = :i",
            i=uuid.UUID(ready["id"]),
        )
    ) == "ready"


async def test_an_environment_without_data_is_not_ready_to_replay(
    client: httpx.AsyncClient, instrument: uuid.UUID
) -> None:
    draft = await contract.make_environment(client, instrument)
    assert draft["status"] == "draft"
    for response in (
        await client.get(f"{API}/environments/{draft['id']}/ticks", headers=viewer()),
        await activate(client, draft["id"]),
    ):
        assert response.status_code == 422
        assert response.json()["type"] == "urn:quantsim:problem:environment-not-ready"


# ---- activation ----


async def test_activation_freezes_the_fingerprint_marks_the_environment_active_and_is_audited(
    client: httpx.AsyncClient, database: Database, ready: dict[str, Any]
) -> None:
    user = uuid.uuid4()
    _, fingerprints = await read_all(client, ready["id"])
    response = await activate(client, ready["id"], user=user)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "active" and body["environment_id"] == ready["id"]
    assert {body["source_fingerprint"]} == fingerprints
    assert body["missing_session_count"] == 0 and body["activated_by"] == str(user)
    listed = (await client.get(f"{API}/environments/{ready['id']}", headers=viewer())).json()
    assert listed["status"] == "active"
    audited = await scalar(
        database,
        "SELECT count(*) FROM audit_log WHERE table_name = 'market_environment' AND row_id = :i"
        " AND operation = 'UPDATE' AND new_data ->> 'status' = 'active' AND changed_by = :u",
        i=ready["id"],
        u=str(user),
    )
    assert audited == 1
    assert (await scalar(database, "SELECT count(*) FROM environment_activation")) == 1


async def test_activating_again_after_the_data_moved_freezes_the_new_fingerprint(
    client: httpx.AsyncClient, database: Database, ready: dict[str, Any]
) -> None:
    first = (await activate(client, ready["id"])).json()
    items, _ = await read_all(client, ready["id"])
    await sql(
        database,
        "UPDATE bar SET adj_close = adj_close * 1.02"
        " WHERE instrument_id = :i AND session_date = :d",
        i=uuid.UUID(items[0]["instrument_id"]),
        d=date.fromisoformat(items[0]["session_date"]),
    )
    page = await client.get(f"{API}/environments/{ready['id']}/ticks", headers=viewer())
    assert page.headers["X-Source-Fingerprint"] != first["source_fingerprint"], (
        "the consumer can tell"
    )
    second = (await activate(client, ready["id"])).json()
    assert second["source_fingerprint"] == page.headers["X-Source-Fingerprint"]
    assert second["activated_at"] >= first["activated_at"]
    assert (await scalar(database, "SELECT count(*) FROM environment_activation")) == 1


async def test_the_activation_table_refuses_what_must_never_be_stored(
    database: Database, ready: dict[str, Any]
) -> None:
    good = "xxh3:" + "0" * 32
    insert = (
        "INSERT INTO environment_activation (environment_id, source_fingerprint,"
        " missing_session_count, activated_by) VALUES (:e, :f, :m, :u)"
    )
    row = {"e": uuid.UUID(ready["id"]), "f": good, "m": 0, "u": uuid.uuid4()}
    for bad, rule in (
        ({"f": "md5:abc"}, "environment_activation_fingerprint_format"),
        ({"f": "xxh3:ABC"}, "environment_activation_fingerprint_format"),
        ({"m": -1}, "environment_activation_missing_not_negative"),
        ({"e": uuid.uuid4()}, "environment_activation_environment_id_fkey"),
    ):
        with pytest.raises(DBAPIError) as caught:
            await sql(database, insert, **(row | bad))
        assert rule in str(caught.value), (bad, str(caught.value)[:200])
    await sql(database, insert, **row)
    with pytest.raises(DBAPIError) as twice:
        await sql(database, insert, **row)
    assert "environment_activation_pkey" in str(twice.value)
    await sql(database, "DELETE FROM market_environment WHERE id = :e", e=row["e"])
    assert (await scalar(database, "SELECT count(*) FROM environment_activation")) == 0


# ---- size (B-NFR-02) ----


async def test_forty_instruments_over_a_few_thousand_sessions_page_within_two_seconds(
    client: httpx.AsyncClient, database: Database
) -> None:
    ids = [await add_instrument(database, f"P{n:02d}") for n in range(40)]
    sessions = 2900
    async with database.transaction() as session:
        await session.execute(
            text(
                "INSERT INTO bar (instrument_id, session_date, ts, open, high, low, close, volume,"
                " adj_open, adj_high, adj_low, adj_close, adj_volume, content_hash, run_id, vendor,"
                " ruleset_version)"
                " SELECT i, d::date, d + interval '21 hours', 10, 12, 9, 11, 1000, 10, 12, 9, 11,"
                " 1000, 'h', :r, 'fixture', 'v1'"
                " FROM unnest(CAST(:ids AS uuid[])) AS i"
                " CROSS JOIN generate_series(date '2010-01-01',"
                " date '2010-01-01' + CAST(:n AS integer),"
                " interval '1 day') AS g(d)"
            ),
            {"ids": ids, "r": uuid.uuid4(), "n": sessions - 1},
        )
    start = date(2010, 1, 1)
    environment = await contract.make_environment(
        client,
        ids[0],
        instruments=ids,
        start=start.isoformat(),
        end=(start + timedelta(days=sessions - 1)).isoformat(),
    )
    assert environment["status"] == "ready"
    total = 40 * sessions
    for after in (0, 60_000, total - 1_999):
        began = time.perf_counter()
        response = await client.get(
            f"{API}/environments/{environment['id']}/ticks",
            params={"after_seq": after, "limit": MAX_LIMIT},
            headers=viewer(),
        )
        elapsed = time.perf_counter() - began
        assert response.status_code == 200 and len(response.json()["items"]) == min(
            MAX_LIMIT, total - after
        )
        assert elapsed < 2.0, f"after_seq={after}: {elapsed:.2f}s"
    last = (
        await client.get(
            f"{API}/environments/{environment['id']}/ticks",
            params={"after_seq": total - 1_999, "limit": MAX_LIMIT},
            headers=viewer(),
        )
    ).json()
    assert last["next_after_seq"] is None and last["items"][-1]["seq"] == total
