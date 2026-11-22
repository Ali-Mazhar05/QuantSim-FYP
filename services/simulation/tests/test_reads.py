"""The read API (B18, B-FR-05, B-FR-14, B-NFR-02, B-NFR-11): the lists, the quantiles and the path
tick feed, on completed runs made by the real job, through the real routes and database."""

import json
import time
import uuid
from datetime import UTC, date, datetime
from typing import Any

import httpx
import pytest
from sqlalchemy import text

from qs_simulation.domain.calendar import step_closes
from qs_template.auth import Role
from tests.auth_support import bearer, make_token
from tests.contract_support import CONTRACTS, tick_problems
from tests.run_support import RUNS, RunWorld, run_body
from tests.test_runs import complete, submit

pytestmark = pytest.mark.db

CALIBRATIONS = "/api/simulation/calibrations"


def reader(role: Role = Role.VIEWER) -> dict[str, str]:
    return bearer(make_token(role))


async def get(w: RunWorld, url: str, *, role: Role = Role.VIEWER, **params: Any) -> httpx.Response:
    return await w.client.get(url, params=params, headers=reader(role))


async def write(w: RunWorld, statement: str, **values: Any) -> None:
    """A statement that changes rows (``RunWorld.sql`` is for reads)."""
    async with w.database.transaction() as session:
        await session.execute(text(statement), values)


async def all_ticks(w: RunWorld, run_id: str, path: int, limit: int = 7) -> list[dict[str, Any]]:
    """Every tick of a path, read page by page the way a consumer would."""
    items: list[dict[str, Any]] = []
    after = 0
    fingerprints = set()
    while True:
        response = await get(w, f"{RUNS}/{run_id}/ticks", path=path, after_seq=after, limit=limit)
        assert response.status_code == 200, response.text
        fingerprints.add(response.headers["X-Source-Fingerprint"])
        page = response.json()
        items += page["items"]
        if page["next_after_seq"] is None:
            break
        assert page["next_after_seq"] == after + len(page["items"])
        after = page["next_after_seq"]
    assert len(fingerprints) == 1  # the same on every page
    assert fingerprints == {items[0]["source_fingerprint"]}
    return items


# ---- the lists ----


async def test_runs_are_listed_newest_first_with_filters_and_paging(run_world: RunWorld) -> None:
    first = await run_world.basket(2)
    second = [(await run_world.instrument("MSFT"))]
    done_one = await complete(run_world, run_body(first, seed=1))
    done_two = await complete(run_world, run_body(second, seed=2))
    waiting = await submit(run_world, run_body(first, seed=3))  # queued: no worker has run it
    listed = (await get(run_world, RUNS)).json()
    assert [r["id"] for r in listed["items"]] == [waiting["id"], done_two["id"], done_one["id"]]
    assert listed["next_cursor"] is None
    by_id = {r["id"]: r for r in listed["items"]}
    assert by_id[done_one["id"]]["symbols"] == done_one["symbols"]
    assert by_id[waiting["id"]]["status"] == "queued"
    assert by_id[waiting["id"]]["symbols"] == waiting["symbols"] != []  # from the request
    assert by_id[done_two["id"]]["median_path_index"] == done_two["median_path_index"]
    only = (await get(run_world, RUNS, status="completed")).json()["items"]
    assert [r["id"] for r in only] == [done_two["id"], done_one["id"]]
    assert (await get(run_world, RUNS, status="failed")).json()["items"] == []
    including = (await get(run_world, RUNS, instrument=str(second[0][0]))).json()["items"]
    assert [r["id"] for r in including] == [done_two["id"]]
    queued_for = (await get(run_world, RUNS, instrument=str(first[0][0]))).json()["items"]
    assert waiting["id"] in [r["id"] for r in queued_for]  # a run not yet generated is found too
    # paging: one at a time, each exactly once, then the end
    seen: list[str] = []
    cursor: str | None = None
    for _ in range(5):
        extra: dict[str, Any] = {} if cursor is None else {"cursor": cursor}
        page = (await get(run_world, RUNS, limit=1, **extra)).json()
        seen += [r["id"] for r in page["items"]]
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert seen == [r["id"] for r in listed["items"]]


async def test_a_bad_cursor_is_422_and_every_role_may_read(run_world: RunWorld) -> None:
    bad = await get(run_world, RUNS, cursor="not-a-cursor")
    assert bad.status_code == 422
    assert bad.json()["type"] == "urn:quantsim:problem:invalid-cursor"
    for role in Role:
        assert (await get(run_world, RUNS, role=role)).status_code == 200
        assert (await get(run_world, CALIBRATIONS, role=role)).status_code == 200


async def test_a_run_the_queue_gave_up_on_is_listed_as_failed(run_world: RunWorld) -> None:
    basket = await run_world.basket(2)
    queued = await submit(run_world, run_body(basket))
    await write(
        run_world,
        "UPDATE job SET status = 'failed', error = 'gave up' WHERE id = :i",
        i=uuid.UUID(queued["id"]),
    )
    items = (await get(run_world, RUNS, status="failed")).json()["items"]
    assert [r["id"] for r in items] == [queued["id"]]
    assert (await get(run_world, f"{RUNS}/{queued['id']}")).json()["status"] == "failed"


async def test_calibrations_are_listed_with_filters_and_paging(run_world: RunWorld) -> None:
    gbm = await run_world.basket(2)
    ou = [await run_world.instrument("KO", model="ou")]
    odd = await run_world.instrument("TSLA", converged=False)
    page = (await get(run_world, CALIBRATIONS)).json()
    ids = {c["id"] for c in page["items"]}
    assert ids == {str(c) for _, c in [*gbm, *ou, odd]}
    assert all(c["status"] == "succeeded" and c["calibration"]["symbol"] for c in page["items"])
    assert [c["id"] for c in (await get(run_world, CALIBRATIONS, model="ou")).json()["items"]] == [
        str(ou[0][1])
    ]
    assert [
        c["id"] for c in (await get(run_world, CALIBRATIONS, converged="false")).json()["items"]
    ] == [str(odd[1])]
    assert [
        c["id"]
        for c in (await get(run_world, CALIBRATIONS, instrument=str(gbm[0][0]))).json()["items"]
    ] == [str(gbm[0][1])]
    seen: list[str] = []
    cursor: str | None = None
    for _ in range(6):
        extra: dict[str, Any] = {} if cursor is None else {"cursor": cursor}
        part = (await get(run_world, CALIBRATIONS, limit=2, **extra)).json()
        seen += [c["id"] for c in part["items"]]
        cursor = part["next_cursor"]
        if cursor is None:
            break
    assert seen == [c["id"] for c in page["items"]] and len(seen) == 4


# ---- the quantiles ----


async def test_quantiles_are_the_stored_fan_per_step_and_instrument(run_world: RunWorld) -> None:
    basket = await run_world.basket(3)
    done = await complete(run_world, run_body(basket, n_paths=300, n_steps=15))
    body = (await get(run_world, f"{RUNS}/{done['id']}/quantiles")).json()
    assert body["run_id"] == done["id"] and body["n_steps"] == 15
    assert [i["symbol"] for i in body["instruments"]] == done["symbols"]
    stored = await run_world.sql(
        "SELECT instrument_id, step, q01, q50, q99 FROM path_quantile WHERE run_id = :r",
        r=uuid.UUID(done["id"]),
    )
    served = {(i["instrument_id"], s["step"]): s for i in body["instruments"] for s in i["steps"]}
    assert len(served) == len(stored) == 3 * 15
    for row in stored:
        point = served[(str(row.instrument_id), row.step)]
        assert (point["q01"], point["q50"], point["q99"]) == tuple(
            format(v, "f") for v in (row.q01, row.q50, row.q99)
        )
    for instrument in body["instruments"]:
        assert [s["step"] for s in instrument["steps"]] == list(range(1, 16))
        for s in instrument["steps"]:
            levels = [float(s[k]) for k in ("q01", "q05", "q25", "q50", "q75", "q95", "q99")]
            assert levels == sorted(levels) and levels[0] > 0
    one = (
        await get(run_world, f"{RUNS}/{done['id']}/quantiles", instrument=str(basket[1][0]))
    ).json()
    assert [i["instrument_id"] for i in one["instruments"]] == [str(basket[1][0])]
    missing = await get(run_world, f"{RUNS}/{done['id']}/quantiles", instrument=str(uuid.uuid4()))
    assert missing.status_code == 404


async def test_quantiles_and_ticks_of_a_run_that_is_not_complete_or_unknown(
    run_world: RunWorld,
) -> None:
    basket = await run_world.basket(2)
    waiting = await submit(run_world, run_body(basket))
    for suffix in ("quantiles", "ticks"):
        extra: dict[str, Any] = {"path": 0} if suffix == "ticks" else {}
        response = await get(run_world, f"{RUNS}/{waiting['id']}/{suffix}", **extra)
        assert response.status_code == 409
        assert response.json()["type"] == "urn:quantsim:problem:run-not-complete"
        assert (await get(run_world, f"{RUNS}/{uuid.uuid4()}/{suffix}", **extra)).status_code == 404


# ---- the tick feed ----


async def test_the_ticks_of_a_path_follow_the_contract_and_read_the_same_at_any_page_size(
    run_world: RunWorld,
) -> None:
    basket = await run_world.basket(3)
    done = await complete(run_world, run_body(basket, n_paths=120, n_steps=12))
    items = await all_ticks(run_world, done["id"], path=5)
    assert len(items) == 12 * 3
    assert [t["seq"] for t in items] == list(range(1, 37))  # no gaps
    assert [(t["session"], t["symbol"]) for t in items] == sorted(
        (t["session"], t["symbol"]) for t in items
    )
    assert {t["symbol"] for t in items} == set(done["symbols"])
    for tick in items:
        assert tick_problems(tick) == [], tick
        assert tick["env_type"] == "synthetic" and tick["env_id"] == done["id"]
        assert tick["path_index"] == 5 and tick["scenario"] is None
        assert tick["open"] == tick["high"] == tick["low"] == tick["close"]
        assert tick["volume"] == "0.00000000"
    stamps = [datetime.fromisoformat(t["ts"]) for t in items]
    assert stamps == sorted(stamps) and all(s.tzinfo is not None for s in stamps)
    for size in (1, 5, 36, 500):  # paging never changes what is read
        assert await all_ticks(run_world, done["id"], path=5, limit=size) == items


async def test_the_served_prices_are_the_stored_ones_and_the_first_step_is_step_one(
    run_world: RunWorld,
) -> None:
    basket = await run_world.basket(2)
    done = await complete(run_world, run_body(basket, n_paths=60, n_steps=6))
    items = await all_ticks(run_world, done["id"], path=3)
    stored = {
        (str(r.instrument_id), r.step): format(r.price, "f")
        for r in await run_world.sql(
            "SELECT instrument_id, step, price FROM path_value"
            " WHERE run_id = :r AND path_index = 3",
            r=uuid.UUID(done["id"]),
        )
    }
    assert {(t["instrument_id"], t["session"] + 1): t["close"] for t in items} == stored


@pytest.mark.parametrize("model", ["gbm", "ou", "merton"])
async def test_ticks_regenerated_from_the_seed_equal_the_stored_ticks(
    run_world: RunWorld, model: str
) -> None:
    basket = await run_world.basket(2, model=model)
    done = await complete(run_world, run_body(basket, model=model, n_paths=520, n_steps=10))
    paths = (0, 249, 250, 519)  # either side of the shard joins, and the last path
    stored = {p: await all_ticks(run_world, done["id"], path=p, limit=50) for p in paths}
    await write(
        run_world,
        "UPDATE run SET storage_mode = 'quantiles' WHERE id = :r",
        r=uuid.UUID(done["id"]),
    )
    for p in paths:  # now nothing is read from path_value: every price is generated again
        assert await all_ticks(run_world, done["id"], path=p, limit=50) == stored[p]


async def test_a_path_outside_the_run_is_404_and_a_missing_path_is_422(run_world: RunWorld) -> None:
    basket = await run_world.basket(2)
    done = await complete(run_world, run_body(basket, n_paths=30, n_steps=4))
    url = f"{RUNS}/{done['id']}/ticks"
    assert (await get(run_world, url, path=29)).status_code == 200
    outside = await get(run_world, url, path=30)
    assert outside.status_code == 404
    assert outside.json()["type"] == "urn:quantsim:problem:not-found"
    assert (await get(run_world, url)).status_code == 422
    past_the_end = await get(run_world, url, path=0, after_seq=8)
    assert past_the_end.status_code == 200 and past_the_end.json() == {
        "items": [],
        "next_after_seq": None,
    }


async def test_the_fingerprint_names_the_run_and_the_same_run_always_has_it(
    run_world: RunWorld,
) -> None:
    basket = await run_world.basket(2)
    one = await complete(run_world, run_body(basket, seed=11, n_paths=40, n_steps=3))
    two = await complete(run_world, run_body(basket, seed=12, n_paths=40, n_steps=3))
    first = await get(run_world, f"{RUNS}/{one['id']}/ticks", path=0)
    again = await get(run_world, f"{RUNS}/{one['id']}/ticks", path=7)
    other = await get(run_world, f"{RUNS}/{two['id']}/ticks", path=0)
    fingerprint = first.headers["X-Source-Fingerprint"]
    assert fingerprint.startswith("xxh3:") and len(fingerprint) == 5 + 32
    assert again.headers["X-Source-Fingerprint"] == fingerprint  # not per path
    assert other.headers["X-Source-Fingerprint"] != fingerprint  # another run


async def test_every_role_reads_the_ticks_and_anonymous_callers_are_refused(
    run_world: RunWorld,
) -> None:
    basket = await run_world.basket(2)
    done = await complete(run_world, run_body(basket, n_paths=30, n_steps=3))
    url = f"{RUNS}/{done['id']}/ticks"
    for role in Role:
        assert (await get(run_world, url, role=role, path=0)).status_code == 200
    assert (await run_world.client.get(url, params={"path": 0})).status_code == 401
    forged = bearer(make_token(Role.QUANT, forged=True))
    assert (await run_world.client.get(url, params={"path": 0}, headers=forged)).status_code == 401


# ---- the dates ----


def test_the_steps_stand_on_the_real_nyse_closes_like_the_recorded_fixture() -> None:
    fixture = json.loads((CONTRACTS / "fixtures" / "synthetic_ticks.json").read_text("utf-8"))
    recorded = [t["ts"] for t in fixture["paths"][0]["items"] if t["symbol"] == "AAPL"]
    closes = step_closes(date(2020, 12, 31), len(recorded))
    assert [c.strftime("%Y-%m-%dT%H:%M:%SZ") for c in closes] == recorded


def test_closes_follow_daylight_saving_and_skip_weekends_and_holidays() -> None:
    closes = step_closes(date(2021, 3, 5), 10)  # 8 March is a Monday, DST began on the 14th
    assert [c.hour for c in closes[:5]] == [21] * 5  # winter: 16:00 New York is 21:00 UTC
    assert [c.hour for c in closes[5:]] == [20] * 5  # summer: 20:00 UTC
    assert all(c.weekday() < 5 for c in closes) and closes == tuple(sorted(closes))
    assert date(2021, 4, 2) not in {
        c.date() for c in step_closes(date(2021, 3, 30), 5)
    }  # Good Friday
    assert all(c.tzinfo is UTC or c.utcoffset().total_seconds() == 0 for c in closes)  # type: ignore[union-attr]
    far = step_closes(date(2026, 12, 31), 2520)  # the longest run reaches past today's calendar
    assert len(far) == 2520 and far[-1].year >= 2036


# ---- time ----


async def test_a_page_of_ticks_is_fast_stored_and_regenerated(run_world: RunWorld) -> None:
    basket = await run_world.basket(8)
    done = await complete(run_world, run_body(basket, n_paths=1000, n_steps=252))
    url = f"{RUNS}/{done['id']}/ticks"
    for mode in ("full", "quantiles"):
        await write(
            run_world,
            "UPDATE run SET storage_mode = :m WHERE id = :r",
            m=mode,
            r=uuid.UUID(done["id"]),
        )
        for after in (0, 1000, 2000):
            started = time.perf_counter()
            response = await get(run_world, url, path=999, after_seq=after, limit=2000)
            elapsed = time.perf_counter() - started
            assert response.status_code == 200 and len(response.json()["items"]) == 2000
            assert elapsed < 2.0, f"{mode} after_seq={after}: {elapsed:.2f}s"
