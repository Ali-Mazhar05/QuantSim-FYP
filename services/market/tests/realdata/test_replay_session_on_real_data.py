"""B13 on recorded data: a replay session run across a real environment (the combination test).

Five recorded names over 2020 go through the real ingestion pipeline, become an environment that is
activated, and a session with an injected clock plays across every session of the year. The dates
the session reports must be the dates of the ticks the feed serves, and the year must have the 253
sessions the NYSE traded in 2020. Skipped without the corpus, as the other real-data tests."""

from datetime import date
from typing import Any

import httpx
import pytest

from qs_market.api_data import MAX_LIMIT
from qs_template.auth import Role
from tests import instrument_support as support
from tests.instrument_support import API, bearer, make_token
from tests.realdata.test_contract_fixtures import (
    REPLAY_SYMBOLS,
    REPLAY_WINDOW,
    load_corpus,
)
from tests.test_feed_contract_api import make_environment
from tests.test_replay_sessions import (  # noqa: F401
    FakeClock,
    activate,
    client,
    clock,
    control,
    read,
    start,
)

database = support.database
pytestmark = pytest.mark.db

NYSE_SESSIONS_2020 = 253


async def test_a_session_runs_across_a_real_year_and_names_the_dates_the_feed_serves(
    client: httpx.AsyncClient,  # noqa: F811
    database: Any,
    clock: FakeClock,  # noqa: F811
) -> None:
    ids = await load_corpus(database)
    environment = await make_environment(
        client,
        ids[REPLAY_SYMBOLS[0]],
        instruments=[ids[s] for s in REPLAY_SYMBOLS],
        start=REPLAY_WINDOW[0].isoformat(),
        end=REPLAY_WINDOW[1].isoformat(),
    )
    assert environment["status"] == "ready"
    frozen = await activate(client, environment["id"])
    served = await client.get(
        f"{API}/environments/{environment['id']}/ticks",
        params={"limit": MAX_LIMIT},
        headers=bearer(make_token(Role.VIEWER)),
    )
    date_of: dict[int, str] = {}
    after = 0
    while True:
        page = await client.get(
            f"{API}/environments/{environment['id']}/ticks",
            params={"after_seq": after, "limit": MAX_LIMIT},
            headers=bearer(make_token(Role.VIEWER)),
        )
        assert page.status_code == 200, page.text
        body = page.json()
        date_of.update({t["session"]: t["session_date"] for t in body["items"]})
        if body["next_after_seq"] is None:
            break
        after = body["next_after_seq"]
    assert served.status_code == 200
    assert sorted(date_of) == list(range(len(date_of)))
    assert date.fromisoformat(date_of[0]).year == 2020

    session = await start(client, environment["id"])
    assert session["session_count"] == len(date_of) == NYSE_SESSIONS_2020
    assert session["source_fingerprint"] == frozen["source_fingerprint"]
    assert session["session_date"] == date_of[0] == "2020-01-02"

    await control(client, session["id"], "speed", speed=20)
    await control(client, session["id"], "play")
    for step in range(1, 13):  # 20 sessions a second
        clock.advance(1)
        now = await read(client, session["id"])
        assert now["position"] == 20 * step and not now["finished"]
        assert now["session_date"] == date_of[20 * step], step
    clock.advance(1)
    end = await read(client, session["id"])
    assert end["finished"] and end["position"] == NYSE_SESSIONS_2020 - 1
    assert end["session_date"] == date_of[NYSE_SESSIONS_2020 - 1] == "2020-12-31"

    # a reload: the page knows only the environment, and finds the clock where the server has it
    clock.advance(30)
    listed = await client.get(
        f"{API}/replay-sessions",
        params={"environment_id": environment["id"]},
        headers=bearer(make_token(Role.VIEWER)),
    )
    [found] = listed.json()
    assert found["id"] == session["id"] and found["position"] == NYSE_SESSIONS_2020 - 1
    back = await control(client, session["id"], "seek", index=0)
    assert back["session_date"] == "2020-01-02" and not back["finished"]
