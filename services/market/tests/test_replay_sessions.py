"""Replay sessions (B13, B-FR-06, B-US-05): a server-side clock over an activated environment.

The clock is injected, so "5x for 2 s advances 10 sessions" is exact, not a wall-clock tolerance.
Pure position tests need no database; the rest run the real routes on a migrated database."""

import asyncio
import time
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
import pytest
from fakeredis import FakeAsyncRedis
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from qs_market.api_data import MAX_LIMIT
from qs_market.main import build_app
from qs_market.replay_sessions import position
from qs_template import Database
from qs_template.auth import Authenticator, Role, StaticKeys
from qs_template.revocation import RevocationList
from tests import instrument_support as support
from tests.instrument_support import API, bearer, make_settings, make_token
from tests.read_support import add_instrument
from tests.test_feed_contract_api import make_environment, ready  # noqa: F401 - a fixture

database = support.database
pytestmark = pytest.mark.db

START = datetime(2026, 11, 19, 9, 0, 0, tzinfo=UTC)


class FakeClock:
    """Server time that moves only when a test says so."""

    def __init__(self) -> None:
        self.now = START

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
async def client(
    database: Database, migrated_database_url: str, clock: FakeClock
) -> Any:  # replaces the shared client: the same app with the fake clock
    settings = make_settings(migrated_database_url)
    app = build_app(
        settings,
        database=database,
        revocations=RevocationList(FakeAsyncRedis()),
        authenticator=Authenticator(settings, jwks=StaticKeys(support._jwks())),
        clock=clock,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://market"
    ) as http:
        yield http


def quant() -> dict[str, str]:
    return bearer(make_token(Role.QUANT))


def viewer() -> dict[str, str]:
    return bearer(make_token(Role.VIEWER))


SESSIONS = f"{API}/replay-sessions"


async def activate(client: httpx.AsyncClient, environment_id: str) -> dict[str, Any]:
    response = await client.post(f"{API}/environments/{environment_id}/activate", headers=quant())
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def start(client: httpx.AsyncClient, environment_id: str, **body: Any) -> dict[str, Any]:
    response = await client.post(
        SESSIONS, json={"environment_id": environment_id, **body}, headers=quant()
    )
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()
    return created


async def control(
    client: httpx.AsyncClient, session_id: str, action: str, **body: Any
) -> dict[str, Any]:
    response = await client.post(
        f"{SESSIONS}/{session_id}/control", json={"action": action, **body}, headers=quant()
    )
    assert response.status_code == 200, response.text
    result: dict[str, Any] = response.json()
    return result


async def read(client: httpx.AsyncClient, session_id: str) -> dict[str, Any]:
    response = await client.get(f"{SESSIONS}/{session_id}", headers=viewer())
    assert response.status_code == 200, response.text
    result: dict[str, Any] = response.json()
    return result


@pytest.fixture
async def live(client: httpx.AsyncClient, ready: dict[str, Any]) -> dict[str, Any]:  # noqa: F811
    """An activated environment and a paused session at its first session."""
    await activate(client, ready["id"])
    return await start(client, ready["id"])


async def ticks_of(client: httpx.AsyncClient, environment_id: str) -> list[dict[str, Any]]:
    response = await client.get(
        f"{API}/environments/{environment_id}/ticks", params={"limit": MAX_LIMIT}, headers=viewer()
    )
    assert response.status_code == 200, response.text
    items: list[dict[str, Any]] = response.json()["items"]
    return items


# ---- the clock, as a pure function ----


def clock_at(seconds: float, **override: Any) -> int:
    values: dict[str, Any] = {
        "anchor_index": 0,
        "anchor_at": START,
        "speed": 1,
        "state": "playing",
        "now": START + timedelta(seconds=seconds),
        "last_index": 100,
    }
    values.update(override)
    return position(**values)


def test_five_times_speed_for_two_seconds_is_ten_sessions() -> None:
    assert clock_at(2, speed=5) == 10


@pytest.mark.parametrize(("speed", "seconds", "expected"), [
    (1, 0, 0), (1, 0.999999, 0), (1, 1, 1), (1, 7.5, 7),
    (5, 0.199999, 0), (5, 0.2, 1), (5, 2.4, 12),
    (20, 0.05, 1), (20, 0.049999, 0), (20, 3, 60),
])  # fmt: skip
def test_the_position_counts_whole_sessions_exactly(
    speed: int, seconds: float, expected: int
) -> None:
    assert clock_at(seconds, speed=speed) == expected


def test_the_position_starts_from_the_anchor() -> None:
    assert clock_at(2, speed=5, anchor_index=30) == 40


def test_a_paused_clock_stands_at_its_anchor_whatever_the_time() -> None:
    assert clock_at(10_000, speed=20, state="paused", anchor_index=12) == 12


def test_the_position_never_passes_the_last_session() -> None:
    assert clock_at(10_000, speed=20, last_index=252) == 252
    assert clock_at(1, anchor_index=252, last_index=252) == 252


def test_a_clock_reading_earlier_than_the_anchor_counts_as_no_time_elapsed() -> None:
    assert clock_at(-3, speed=20, anchor_index=4) == 4


# ---- creating a session ----


async def test_a_new_session_is_paused_at_the_first_session_of_the_frozen_data(
    client: httpx.AsyncClient,
    ready: dict[str, Any],  # noqa: F811
) -> None:
    activation = await activate(client, ready["id"])
    ticks = await ticks_of(client, ready["id"])
    session = await start(client, ready["id"])
    assert session["state"] == "paused" and session["speed"] == 1 and not session["finished"]
    assert session["position"] == 0 and session["session_date"] == ticks[0]["session_date"]
    assert session["session_count"] == max(t["session"] for t in ticks) + 1
    assert session["source_fingerprint"] == activation["source_fingerprint"]
    assert session["current_fingerprint"] == activation["source_fingerprint"]
    assert session["environment_id"] == ready["id"]
    assert session["server_time"].startswith("2026-11-19T09:00:00")


async def test_a_session_may_start_at_a_chosen_speed(
    client: httpx.AsyncClient,
    ready: dict[str, Any],  # noqa: F811
) -> None:
    await activate(client, ready["id"])
    assert (await start(client, ready["id"], speed=20))["speed"] == 20


async def test_an_environment_must_be_activated_before_it_is_replayed(
    client: httpx.AsyncClient,
    ready: dict[str, Any],  # noqa: F811
) -> None:
    response = await client.post(SESSIONS, json={"environment_id": ready["id"]}, headers=quant())
    assert response.status_code == 422
    assert response.json()["type"] == "urn:quantsim:problem:environment-not-active"


async def test_what_cannot_be_replayed_cannot_have_a_session(
    client: httpx.AsyncClient, database: Database
) -> None:
    instrument = await add_instrument(database, "ZZNONE")
    unknown = await client.post(
        SESSIONS, json={"environment_id": str(uuid.uuid4())}, headers=quant()
    )
    assert unknown.status_code == 404
    refused = {
        "draft": await make_environment(client, instrument),  # no bars: not ready
        "hourly": await make_environment(client, instrument, frequency="hourly"),
        "synthetic": await make_environment(client, instrument, kind="synthetic"),
    }
    for label, environment in refused.items():
        response = await client.post(
            SESSIONS, json={"environment_id": environment["id"]}, headers=quant()
        )
        assert response.status_code == 422, (label, response.text)


@pytest.mark.parametrize("speed", [0, 2, 3, 10, 100, -1, "fast"])
async def test_only_the_three_speeds_are_accepted(
    client: httpx.AsyncClient,
    ready: dict[str, Any],  # noqa: F811
    speed: Any,
) -> None:
    await activate(client, ready["id"])
    made = await client.post(
        SESSIONS, json={"environment_id": ready["id"], "speed": speed}, headers=quant()
    )
    assert made.status_code == 422, speed


# ---- the clock, through the routes ----


async def test_five_times_speed_for_two_seconds_advances_ten_sessions(
    client: httpx.AsyncClient, clock: FakeClock, live: dict[str, Any]
) -> None:
    await control(client, live["id"], "speed", speed=5)
    await control(client, live["id"], "play")
    clock.advance(2)
    session = await read(client, live["id"])
    assert session["position"] == 10 and session["state"] == "playing"
    assert session["speed"] == 5 and not session["finished"]


async def test_pause_freezes_the_position(
    client: httpx.AsyncClient, clock: FakeClock, live: dict[str, Any]
) -> None:
    await control(client, live["id"], "play")
    clock.advance(3)
    paused = await control(client, live["id"], "pause")
    assert paused["state"] == "paused" and paused["position"] == 3
    clock.advance(500)
    assert (await read(client, live["id"]))["position"] == 3


async def test_play_after_a_pause_continues_from_where_it_stopped(
    client: httpx.AsyncClient, clock: FakeClock, live: dict[str, Any]
) -> None:
    await control(client, live["id"], "play")
    clock.advance(3)
    await control(client, live["id"], "pause")
    clock.advance(60)
    await control(client, live["id"], "play")
    clock.advance(2)
    assert (await read(client, live["id"]))["position"] == 5


async def test_seek_then_play_continues_from_the_seek(
    client: httpx.AsyncClient, clock: FakeClock, live: dict[str, Any]
) -> None:
    sought = await control(client, live["id"], "seek", index=7)
    assert sought["position"] == 7 and sought["state"] == "paused"
    await control(client, live["id"], "play")
    clock.advance(2)
    assert (await read(client, live["id"]))["position"] == 9


async def test_a_seek_while_playing_moves_the_clock_and_keeps_it_running(
    client: httpx.AsyncClient, clock: FakeClock, live: dict[str, Any]
) -> None:
    await control(client, live["id"], "play")
    clock.advance(4)
    sought = await control(client, live["id"], "seek", index=15)
    assert sought["position"] == 15 and sought["state"] == "playing"
    clock.advance(2)
    assert (await read(client, live["id"]))["position"] == 17


async def test_a_speed_change_re_anchors_without_a_jump(
    client: httpx.AsyncClient, clock: FakeClock, live: dict[str, Any]
) -> None:
    await control(client, live["id"], "play")
    clock.advance(3)
    faster = await control(client, live["id"], "speed", speed=5)
    assert faster["position"] == 3 and faster["speed"] == 5  # no jump at the change
    clock.advance(1)
    assert (await read(client, live["id"]))["position"] == 8
    clock.advance(1)
    slower = await control(client, live["id"], "speed", speed=1)
    assert slower["position"] == 13
    clock.advance(2)
    assert (await read(client, live["id"]))["position"] == 15


async def test_a_speed_change_while_paused_changes_nothing_but_the_speed(
    client: httpx.AsyncClient, clock: FakeClock, live: dict[str, Any]
) -> None:
    await control(client, live["id"], "seek", index=4)
    changed = await control(client, live["id"], "speed", speed=20)
    assert changed["speed"] == 20 and changed["position"] == 4 and changed["state"] == "paused"
    clock.advance(10)
    assert (await read(client, live["id"]))["position"] == 4


async def test_a_repeated_control_does_not_lose_the_part_of_a_session_that_has_elapsed(
    client: httpx.AsyncClient, clock: FakeClock, live: dict[str, Any]
) -> None:
    await control(client, live["id"], "play")
    clock.advance(0.5)
    await control(client, live["id"], "play")  # a double click
    await control(client, live["id"], "speed", speed=1)  # the same speed again
    clock.advance(0.5)
    assert (await read(client, live["id"]))["position"] == 1
    await control(client, live["id"], "pause")
    again = await control(client, live["id"], "pause")
    assert again["state"] == "paused" and again["position"] == 1


async def test_the_end_clamps_and_is_reported_as_finished(
    client: httpx.AsyncClient, clock: FakeClock, live: dict[str, Any]
) -> None:
    ticks = await ticks_of(client, live["environment_id"])
    last = live["session_count"] - 1
    await control(client, live["id"], "speed", speed=20)
    await control(client, live["id"], "play")
    clock.advance(1)
    mid = await read(client, live["id"])
    assert mid["position"] == 20 and not mid["finished"]
    clock.advance(10_000)
    done = await read(client, live["id"])
    assert done["position"] == last and done["finished"] and done["state"] == "playing"
    assert done["session_date"] == ticks[-1]["session_date"]
    clock.advance(10_000)
    assert (await read(client, live["id"]))["position"] == last  # it stays there
    restarted = await control(client, live["id"], "seek", index=0)
    assert restarted["position"] == 0 and not restarted["finished"]


async def test_seek_clamps_to_the_first_and_last_session(
    client: httpx.AsyncClient, live: dict[str, Any]
) -> None:
    last = live["session_count"] - 1
    assert (await control(client, live["id"], "seek", index=10**9))["position"] == last
    assert (await control(client, live["id"], "seek", index=-5))["position"] == 0
    assert (await control(client, live["id"], "seek", index=last))["position"] == last


async def test_the_session_date_follows_the_position_through_the_whole_window(
    client: httpx.AsyncClient, live: dict[str, Any]
) -> None:
    ticks = await ticks_of(client, live["environment_id"])
    date_of = {t["session"]: t["session_date"] for t in ticks}
    assert len(date_of) == live["session_count"]
    for index in sorted(date_of):
        sought = await control(client, live["id"], "seek", index=index)
        assert sought["session_date"] == date_of[index], index


async def test_a_reload_finds_the_session_and_resumes_at_the_server_position(
    client: httpx.AsyncClient, clock: FakeClock, live: dict[str, Any]
) -> None:
    await control(client, live["id"], "speed", speed=5)
    await control(client, live["id"], "play")
    clock.advance(1.5)
    # a fresh page knows only the environment: it lists the sessions and reads the first
    listed = await client.get(
        SESSIONS, params={"environment_id": live["environment_id"]}, headers=viewer()
    )
    assert listed.status_code == 200
    [found] = listed.json()
    assert found["id"] == live["id"] and found["position"] == 7 and found["state"] == "playing"
    assert found["server_time"] != live["server_time"]
    other = await client.get(
        SESSIONS, params={"environment_id": str(uuid.uuid4())}, headers=viewer()
    )
    assert other.json() == []


async def test_the_newest_session_of_an_environment_is_listed_first(
    client: httpx.AsyncClient, clock: FakeClock, live: dict[str, Any]
) -> None:
    clock.advance(5)
    newer = await start(client, live["environment_id"])
    listed = await client.get(SESSIONS, headers=viewer())
    assert [s["id"] for s in listed.json()] == [newer["id"], live["id"]]


async def test_two_sessions_of_one_environment_run_independently(
    client: httpx.AsyncClient, clock: FakeClock, live: dict[str, Any]
) -> None:
    other = await start(client, live["environment_id"])
    await control(client, live["id"], "seek", index=9)
    assert (await read(client, other["id"]))["position"] == 0
    assert (await read(client, live["id"]))["position"] == 9


async def test_simultaneous_controls_both_land_and_leave_a_valid_clock(
    client: httpx.AsyncClient, clock: FakeClock, live: dict[str, Any]
) -> None:
    answers = await asyncio.gather(
        client.post(
            f"{SESSIONS}/{live['id']}/control",
            json={"action": "speed", "speed": 5},
            headers=quant(),
        ),
        client.post(
            f"{SESSIONS}/{live['id']}/control", json={"action": "seek", "index": 6}, headers=quant()
        ),
        client.post(f"{SESSIONS}/{live['id']}/control", json={"action": "play"}, headers=quant()),
    )
    assert [a.status_code for a in answers] == [200, 200, 200]
    final = await read(client, live["id"])
    assert final["speed"] == 5 and final["state"] == "playing" and final["position"] == 6


# ---- what the controls refuse ----


async def test_a_bad_control_is_refused_with_422_and_changes_nothing(
    client: httpx.AsyncClient, live: dict[str, Any]
) -> None:
    for body in (
        {"action": "rewind"},
        {"action": "speed"},
        {"action": "speed", "speed": 3},
        {"action": "seek"},
        {"action": "seek", "index": "start"},
        {},
    ):
        response = await client.post(f"{SESSIONS}/{live['id']}/control", json=body, headers=quant())
        assert response.status_code == 422, body
    assert (await read(client, live["id"]))["updated_at"] == live["updated_at"]


async def test_an_unknown_session_is_404_everywhere(client: httpx.AsyncClient) -> None:
    ghost = uuid.uuid4()
    assert (await client.get(f"{SESSIONS}/{ghost}", headers=viewer())).status_code == 404
    response = await client.post(
        f"{SESSIONS}/{ghost}/control", json={"action": "play"}, headers=quant()
    )
    assert response.status_code == 404
    assert (await client.get(f"{SESSIONS}/not-a-uuid", headers=viewer())).status_code == 422


# ---- who may do what (B-US-05, X4) ----


async def test_everyone_signed_in_reads_but_only_quants_and_admins_control(
    client: httpx.AsyncClient,
    ready: dict[str, Any],  # noqa: F811
) -> None:
    await activate(client, ready["id"])
    for role in (Role.VIEWER, Role.ANALYST):
        denied = bearer(make_token(role))
        made = await client.post(SESSIONS, json={"environment_id": ready["id"]}, headers=denied)
        assert made.status_code == 403, role
    session = await start(client, ready["id"])
    for role in (Role.VIEWER, Role.ANALYST, Role.QUANT, Role.ADMIN):
        headers = bearer(make_token(role))
        assert (await client.get(SESSIONS, headers=headers)).status_code == 200, role
        one = await client.get(f"{SESSIONS}/{session['id']}", headers=headers)
        assert one.status_code == 200, role
    for role in (Role.VIEWER, Role.ANALYST):
        headers = bearer(make_token(role))
        for body in ({"action": "play"}, {"action": "seek", "index": 3}):
            response = await client.post(
                f"{SESSIONS}/{session['id']}/control", json=body, headers=headers
            )
            assert response.status_code == 403, (role, body)
    for role in (Role.QUANT, Role.ADMIN):
        response = await client.post(
            f"{SESSIONS}/{session['id']}/control",
            json={"action": "pause"},
            headers=bearer(make_token(role)),
        )
        assert response.status_code == 200, role
    assert (await read(client, session["id"]))["position"] == 0  # a refused control changed nothing
    for headers in ({}, bearer(make_token(Role.ADMIN, forged=True))):
        assert (await client.get(SESSIONS, headers=headers)).status_code == 401
        none = await client.post(
            f"{SESSIONS}/{session['id']}/control", json={"action": "play"}, headers=headers
        )
        assert none.status_code == 401


# ---- the data a session stands on ----


async def test_a_session_shows_when_its_environment_was_activated_again(
    client: httpx.AsyncClient, database: Database, live: dict[str, Any]
) -> None:
    ticks = await ticks_of(client, live["environment_id"])
    async with database.transaction() as session:
        await session.execute(
            text(
                "UPDATE bar SET adj_close = adj_close * 1.01"
                " WHERE instrument_id = :i AND session_date = :d"
            ),
            {
                "i": uuid.UUID(ticks[3]["instrument_id"]),
                "d": date.fromisoformat(ticks[3]["session_date"]),
            },
        )
    unchanged = await read(client, live["id"])  # activation not repeated: still the frozen one
    assert unchanged["current_fingerprint"] == unchanged["source_fingerprint"]
    refrozen = await activate(client, live["environment_id"])
    after = await read(client, live["id"])
    assert after["source_fingerprint"] == live["source_fingerprint"]
    assert after["current_fingerprint"] == refrozen["source_fingerprint"]
    assert after["current_fingerprint"] != after["source_fingerprint"]
    # a session made now stands on the new data
    assert (await start(client, live["environment_id"]))["source_fingerprint"] == (
        refrozen["source_fingerprint"]
    )


# ---- the database refuses what the API never sends ----


async def run_sql(database: Database, statement: str, **values: Any) -> None:
    async with database.transaction() as session:
        await session.execute(text(statement), values)


INSERT = (
    "INSERT INTO replay_session (id, environment_id, anchor_index, anchor_at, speed, state,"
    " session_count, source_fingerprint, created_by) VALUES (:id, :env, :a, now(), :speed, :state,"
    " :n, :fp, :who)"
)
GOOD = {"a": 0, "speed": 1, "state": "paused", "n": 10, "fp": "xxh3:" + "0" * 32}


@pytest.mark.parametrize(
    ("override", "constraint"),
    [
        ({"speed": 3}, "replay_session_speed_valid"),
        ({"speed": 0}, "replay_session_speed_valid"),
        ({"state": "rewinding"}, "replay_session_state_valid"),
        ({"a": -1}, "replay_session_anchor_in_range"),
        ({"a": 10}, "replay_session_anchor_in_range"),
        # no session count can hold an anchor, so both checks refuse it; either name will do
        ({"n": 0, "a": 0}, "replay_session_(has_sessions|anchor_in_range)"),
        ({"fp": "xxh3:abc"}, "replay_session_fingerprint_format"),
        ({"fp": "md5:" + "0" * 32}, "replay_session_fingerprint_format"),
    ],
)
async def test_the_database_refuses_an_invalid_session(
    database: Database,
    client: httpx.AsyncClient,
    ready: dict[str, Any],  # noqa: F811
    override: dict[str, Any],
    constraint: str,
) -> None:
    values: dict[str, Any] = {
        "id": uuid.uuid4(),
        "env": uuid.UUID(ready["id"]),
        "who": uuid.uuid4(),
    }
    values.update(GOOD)
    values.update(override)
    with pytest.raises(DBAPIError, match=constraint):
        await run_sql(database, INSERT, **values)


async def test_a_session_must_belong_to_a_real_environment_and_follows_it_out(
    database: Database,
    client: httpx.AsyncClient,
    live: dict[str, Any],
) -> None:
    values = {"id": uuid.uuid4(), "env": uuid.uuid4(), "who": uuid.uuid4(), **GOOD}
    with pytest.raises(DBAPIError, match="foreign key"):
        await run_sql(database, INSERT, **values)
    await run_sql(
        database,
        "DELETE FROM market_environment WHERE id = :e",
        e=uuid.UUID(live["environment_id"]),
    )
    async with database.transaction() as session:
        left = await session.execute(text("SELECT count(*) FROM replay_session"))
        assert left.scalar_one() == 0


async def test_every_change_of_a_session_is_audited_with_who_made_it(
    client: httpx.AsyncClient,
    database: Database,
    ready: dict[str, Any],  # noqa: F811
) -> None:
    await activate(client, ready["id"])
    actor = uuid.uuid4()
    made = await client.post(
        SESSIONS,
        json={"environment_id": ready["id"]},
        headers=bearer(make_token(Role.QUANT, user_id=actor)),
    )
    assert made.status_code == 201, made.text
    await client.post(
        f"{SESSIONS}/{made.json()['id']}/control",
        json={"action": "seek", "index": 2},
        headers=bearer(make_token(Role.ADMIN)),
    )
    async with database.transaction() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT operation, changed_by FROM audit_log"
                    " WHERE table_name = 'replay_session' AND row_id = :row ORDER BY id"
                ),
                {"row": made.json()["id"]},
            )
        ).all()
    assert [r.operation for r in rows] == ["INSERT", "UPDATE"]
    assert rows[0].changed_by == str(actor)


# ---- size: a poll must stay cheap on the biggest window (B-NFR-02) ----


async def test_reading_a_session_over_forty_instruments_stays_fast(
    client: httpx.AsyncClient, database: Database, clock: FakeClock
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
                " date '2010-01-01' + CAST(:n AS integer), interval '1 day') AS g(d)"
            ),
            {"ids": ids, "r": uuid.uuid4(), "n": sessions - 1},
        )
        await session.execute(text("ANALYZE bar"))
    start_day = date(2010, 1, 1)
    environment = await make_environment(
        client,
        ids[0],
        instruments=ids,
        start=start_day.isoformat(),
        end=(start_day + timedelta(days=sessions - 1)).isoformat(),
    )
    await activate(client, environment["id"])
    live_session = await start(client, environment["id"])
    assert live_session["session_count"] == sessions
    await control(client, live_session["id"], "speed", speed=20)
    await control(client, live_session["id"], "play")
    clock.advance(100)  # 2,000 sessions in
    for _ in range(3):
        began = time.perf_counter()
        polled = await read(client, live_session["id"])
        elapsed = time.perf_counter() - began
        assert polled["position"] == 2000
        assert polled["session_date"] == (start_day + timedelta(days=2000)).isoformat()
        assert elapsed < 0.5, f"a poll took {elapsed:.2f}s"
