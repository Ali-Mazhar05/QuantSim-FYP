"""The live tick feed against the committed synthetic fixture (C3, tracker I-16).

The fixture is illustrative: three correlated GBM paths made with a self-contained generator and
seed 42, and other lanes read its numbers (Lane A's demo feed copies it, Lane C's K5 end-to-end test
fits it). So the live feed is held equal to it in everything except the random prices and the run's
identity: the same keys, the same order, the same `seq`, `session`, `ts` (the real NYSE closes after
2020-12-31), symbols, flat bars, zero volume and path index, and prices at the same scale. A change
to any of those would change what Lane A reads and fails here first."""

import json

import numpy as np
import pytest

from qs_template.auth import Role
from tests.auth_support import bearer, make_token
from tests.contract_support import CONTRACTS, tick_problems
from tests.run_support import RUNS, RunWorld, run_body
from tests.test_runs import complete

pytestmark = pytest.mark.db
FIXTURE = json.loads((CONTRACTS / "fixtures" / "synthetic_ticks.json").read_text("utf-8"))
SYMBOLS = FIXTURE["run"]["symbols"]
STEPS = FIXTURE["run"]["n_steps"]
# the fixture starts from the last close of 2020: so do the instruments' calibration windows
SESSIONS_2020 = int(np.busday_count("2020-01-02", "2021-01-01"))


async def test_the_live_ticks_have_the_shape_of_the_recorded_fixture(run_world: RunWorld) -> None:
    basket = [await run_world.instrument(symbol, n=SESSIONS_2020) for symbol in SYMBOLS]
    done = await complete(run_world, run_body(basket, n_paths=20, n_steps=STEPS))
    assert done["status"] == "completed", done
    live: list[dict[str, object]] = []
    after = 0
    while True:
        page = (
            await run_world.client.get(
                f"{RUNS}/{done['id']}/ticks",
                params={"path": 0, "after_seq": after, "limit": 500},
                headers=bearer(make_token(Role.VIEWER)),
            )
        ).json()
        live += page["items"]
        if page["next_after_seq"] is None:
            break
        after = page["next_after_seq"]
    recorded = FIXTURE["paths"][0]["items"]

    assert len(live) == len(recorded) == STEPS * len(SYMBOLS)
    for mine, theirs in zip(live, recorded, strict=True):
        assert tick_problems(mine) == []
        # the same fields in the same order
        assert [k for k in mine if k != "session_date"] == list(theirs)
        for field in (
            "env_type",
            "seq",
            "session",
            "ts",
            "symbol",
            "volume",
            "scenario",
            "path_index",
        ):
            assert mine[field] == theirs[field], (field, mine, theirs)
        assert mine["open"] == mine["high"] == mine["low"] == mine["close"]
        for price in ("open", "close"):
            assert len(str(mine[price]).split(".")[1]) == len(str(theirs[price]).split(".")[1])
        assert str(mine["source_fingerprint"]).startswith("xxh3:")
        assert len(str(mine["source_fingerprint"])) == len(str(theirs["source_fingerprint"]))
    assert {t["env_id"] for t in live} == {
        done["id"]
    }  # the run's id, as the fixture's `env_id` is its run's
