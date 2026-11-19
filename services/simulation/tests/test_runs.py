"""Monte Carlo runs end to end (B16; B-FR-11, 13, 14; B-NFR-01, 05, 09, 13):
the real routes, queue, worker and a migrated database, around prices and correlations the test
controls."""

import asyncio
import time
import uuid
from typing import Any

import httpx
import numpy as np
import pytest
from sqlalchemy import text

import qs_simulation.runs as runs_module
from qs_simulation.composition import Dependencies, build_handlers
from qs_simulation.domain.runs import to_price
from qs_simulation.runs import regenerate
from qs_template.auth import Role
from qs_template.jobs import Worker
from tests.auth_support import bearer, make_token
from tests.run_support import PARAMS, RUNS, RunWorld, run_body

pytestmark = pytest.mark.db


def quant(user: uuid.UUID | None = None) -> dict[str, str]:
    return bearer(make_token(Role.QUANT, user_id=user))


async def submit(w: RunWorld, body: dict[str, Any], **headers: str) -> dict[str, Any]:
    response = await w.client.post(RUNS, json=body, headers={**quant(), **headers})
    assert response.status_code == 202, response.text
    result: dict[str, Any] = response.json()
    return result


async def poll(w: RunWorld, run_id: str) -> dict[str, Any]:
    response = await w.client.get(f"{RUNS}/{run_id}", headers=bearer(make_token(Role.VIEWER)))
    assert response.status_code == 200, response.text
    result: dict[str, Any] = response.json()
    return result


async def complete(w: RunWorld, body: dict[str, Any]) -> dict[str, Any]:
    queued = await submit(w, body)
    await w.run_jobs()
    return await poll(w, queued["id"])


async def count(w: RunWorld, table: str, run_id: str) -> int:
    [row] = await w.sql(
        f"SELECT count(*) AS n FROM {table} WHERE run_id = :r",  # noqa: S608 - fixed table names
        r=uuid.UUID(run_id),
    )
    return int(row.n)


async def fingerprint_of_paths(w: RunWorld, run_id: str) -> str:
    [row] = await w.sql(
        "SELECT md5(string_agg(price::text, ',' ORDER BY instrument_id, path_index, step)) AS h"
        " FROM path_value WHERE run_id = :r",
        r=uuid.UUID(run_id),
    )
    return str(row.h)


# ---- a run, start to finish ----


async def test_a_run_completes_with_statistics_quantiles_a_median_path_and_its_correlation(
    run_world: RunWorld,
) -> None:
    basket = await run_world.basket(3)
    done = await complete(run_world, run_body(basket))
    assert done["status"] == "completed" and done["progress"] == 1.0 and done["error"] is None
    assert done["seed"] == 7 and done["storage_mode"] == "full"
    assert (done["model"], done["n_paths"], done["n_steps"]) == ("gbm", 200, 20)
    assert done["parent_run_id"] is None and done["scenario"] is None
    assert [s["instrument_id"] for s in done["statistics"]] == [str(i) for i, _ in basket]
    assert done["symbols"] == [s["symbol"] for s in done["statistics"]]
    assert 0 <= done["median_path_index"] < 200
    for stat in done["statistics"]:
        p5, med, p95 = (float(stat[k]) for k in ("p5_price", "median_price", "p95_price"))
        assert 0 < p5 <= med <= p95 and float(stat["var95"]) <= float(stat["cvar95"])
    rid = done["id"]
    assert await count(run_world, "run_instrument", rid) == 3
    assert await count(run_world, "run_statistics", rid) == 3
    assert await count(run_world, "path_quantile", rid) == 20 * 3
    assert await count(run_world, "path_value", rid) == 200 * 20 * 3
    [corr] = await run_world.sql(
        "SELECT * FROM run_correlation WHERE run_id = :r", r=uuid.UUID(rid)
    )
    assert corr.size == 3 and corr.repair_applied is False
    assert np.array(corr.matrix) == pytest.approx(np.full((3, 3), 0.5) + 0.5 * np.eye(3))


async def test_the_start_price_is_the_calibrated_windows_last_adjusted_close(
    run_world: RunWorld,
) -> None:
    basket = await run_world.basket(2)
    done = await complete(run_world, run_body(basket))
    for instrument_id, _ in basket:
        last = run_world.source.points[instrument_id][-1]
        [row] = await run_world.sql(
            "SELECT s0 FROM run_instrument WHERE run_id = :r AND instrument_id = :i",
            r=uuid.UUID(done["id"]),
            i=instrument_id,
        )
        assert row.s0 == last.adj_close.quantize(row.s0)


async def test_progress_and_completion_are_announced_through_the_outbox(
    run_world: RunWorld,
) -> None:
    basket = await run_world.basket(2)
    done = await complete(run_world, run_body(basket, n_paths=1000, n_steps=5))
    progress = [e["data"]["progress"] for e in await run_world.events("sim.progress", done["id"])]
    assert progress == sorted(progress) and progress[0] <= 0.1 and progress[-1] >= 0.9
    assert len({int(p * 10) for p in progress}) >= 6  # about every tenth of the work
    [completed] = await run_world.events("sim.completed", done["id"])
    assert completed["data"]["median_path_index"] == done["median_path_index"]
    assert completed["data"]["symbols"] == done["symbols"] and completed["producer"] == "simulation"
    assert completed["aggregate_type"] == "run" and completed["data"]["storage_mode"] == "full"
    assert await run_world.events("sim.failed", done["id"]) == []


async def test_a_single_instrument_run_needs_no_correlation(run_world: RunWorld) -> None:
    done = await complete(run_world, run_body(await run_world.basket(1)))
    assert done["status"] == "completed" and run_world.correlations.calls == 0
    [corr] = await run_world.sql("SELECT matrix FROM run_correlation")
    assert corr.matrix == [[1.0]]


async def test_every_model_runs(run_world: RunWorld) -> None:
    for model in PARAMS:
        done = await complete(
            run_world, run_body(await run_world.basket(2, model=model), model=model)
        )
        assert done["status"] == "completed", model
        assert all(float(s["median_price"]) > 0 for s in done["statistics"])


# ---- the correlation window ----


async def test_the_default_window_is_the_overlap_of_the_calibration_windows(
    run_world: RunWorld,
) -> None:
    a, _ = await run_world.instrument("AAPL", n=300)
    b, _ = await run_world.instrument("MSFT", n=250)
    basket = [(a, await _calibration_of(run_world, a)), (b, await _calibration_of(run_world, b))]
    await complete(run_world, run_body(basket))
    [(ids, start, end)] = run_world.correlations.asked
    assert ids == [a, b]
    assert start == run_world.source.points[a][0].session_date
    assert end == run_world.source.points[b][-1].session_date  # the shorter window ends first


async def test_an_explicit_window_is_the_one_the_matrix_is_measured_over(
    run_world: RunWorld,
) -> None:
    basket = await run_world.basket(2)
    window = {"start": "2020-03-02", "end": "2020-09-30"}
    await complete(run_world, run_body(basket, correlation_window=window))
    [(_, start, end)] = run_world.correlations.asked
    assert (start.isoformat(), end.isoformat()) == ("2020-03-02", "2020-09-30")


async def _calibration_of(w: RunWorld, instrument_id: uuid.UUID) -> uuid.UUID:
    [row] = await w.sql("SELECT id FROM calibration WHERE instrument_id = :i", i=instrument_id)
    return uuid.UUID(str(row.id))


# ---- what a submit refuses (and queues nothing) ----


@pytest.mark.parametrize(
    "override",
    [
        {"n_paths": 19},
        {"n_paths": 100_001},
        {"n_steps": 0},
        {"n_steps": 2_521},
        {"seed": -1},
        {"seed": 2**63},
        {"model": "garch"},
        {"instruments": []},
        {"correlation_window": {"start": "2020-06-01", "end": "2020-01-01"}},
        {"n_paths": "many"},
    ],
)
async def test_a_bad_request_is_422_and_queues_nothing(
    run_world: RunWorld, override: dict[str, Any]
) -> None:
    body = run_body(await run_world.basket(2), **override)
    response = await run_world.client.post(RUNS, json=body, headers=quant())
    assert response.status_code == 422, override
    assert await run_world.sql("SELECT 1 FROM run") == []
    assert await run_world.sql("SELECT 1 FROM job") == []


async def test_more_than_forty_instruments_is_422(run_world: RunWorld) -> None:
    one = await run_world.instrument()
    response = await run_world.client.post(RUNS, json=run_body([one] * 41), headers=quant())
    assert response.status_code == 422


async def test_an_instrument_twice_is_refused(run_world: RunWorld) -> None:
    one = await run_world.instrument()
    response = await run_world.client.post(RUNS, json=run_body([one, one]), headers=quant())
    assert response.status_code == 422 and "twice" in response.json()["detail"]


async def test_a_run_against_another_instruments_calibration_is_refused(
    run_world: RunWorld,
) -> None:
    (a, ca), (b, cb) = await run_world.basket(2)
    response = await run_world.client.post(RUNS, json=run_body([(a, cb), (b, ca)]), headers=quant())
    assert response.status_code == 422
    assert "another instrument" in response.json()["detail"]
    assert response.json()["type"] == "urn:quantsim:problem:invalid-run"


async def test_a_calibration_of_another_model_that_did_not_converge_or_does_not_exist_is_refused(
    run_world: RunWorld,
) -> None:
    ou = await run_world.instrument("OU", model="ou")
    lost = await run_world.instrument("LOST", converged=False)
    ghost = (await run_world.instrument("GHOST"))[0], uuid.uuid4()
    for basket, fragment in (
        ([ou], "is a ou fit"),
        ([lost], "did not converge"),
        ([ghost], "does not exist"),
    ):
        response = await run_world.client.post(RUNS, json=run_body(basket), headers=quant())
        assert response.status_code == 422 and fragment in response.json()["detail"], fragment


async def test_a_run_too_large_for_the_deployment_is_refused_with_its_own_type(
    run_world: RunWorld,
) -> None:
    body = run_body(await run_world.basket(40), n_paths=100_000, n_steps=2_520)
    response = await run_world.client.post(RUNS, json=body, headers=quant())
    assert response.status_code == 422
    assert response.json()["type"] == "urn:quantsim:problem:run-too-large"


# ---- submit: speed and idempotency (B-NFR-01, B-NFR-09) ----


async def test_a_submit_answers_202_at_once_with_a_queued_run_and_does_no_work(
    run_world: RunWorld,
) -> None:
    basket = await run_world.basket(3)
    began = time.perf_counter()
    response = await run_world.client.post(RUNS, json=run_body(basket), headers=quant())
    elapsed = time.perf_counter() - began
    assert response.status_code == 202 and elapsed < 0.8, f"{elapsed:.2f}s"
    body = response.json()
    assert response.headers["Location"] == f"/api/simulation/runs/{body['id']}"
    assert body["status"] == "queued" and body["progress"] == 0 and body["statistics"] == []
    assert body["symbols"] == [s for s in body["symbols"]] and len(body["symbols"]) == 3
    assert body["median_path_index"] is None and body["seed"] == 7
    assert run_world.correlations.calls == 0  # nothing ran in the request


async def test_the_seed_is_drawn_when_it_is_left_out_and_is_reported(run_world: RunWorld) -> None:
    basket = await run_world.basket(1)
    body = run_body(basket)
    del body["seed"]
    first, second = await submit(run_world, body), await submit(run_world, body)
    assert first["seed"] != second["seed"] and 0 <= first["seed"] < 2**63


async def test_the_same_idempotency_key_returns_the_same_run(run_world: RunWorld) -> None:
    body = run_body(await run_world.basket(2))
    user = uuid.uuid4()
    first = await run_world.client.post(
        RUNS, json=body, headers={**quant(user), "Idempotency-Key": "k1"}
    )
    again = await run_world.client.post(
        RUNS, json=body, headers={**quant(user), "Idempotency-Key": "k1"}
    )
    assert first.status_code == again.status_code == 202
    assert first.json()["id"] == again.json()["id"]
    await run_world.run_jobs()
    late = await run_world.client.post(
        RUNS, json=body, headers={**quant(user), "Idempotency-Key": "k1"}
    )
    assert late.json()["id"] == first.json()["id"] and late.json()["status"] == "completed"
    assert len(await run_world.sql("SELECT 1 FROM run")) == 1
    assert len(await run_world.sql("SELECT 1 FROM job")) == 1


async def test_a_key_may_be_repeated_without_the_seed_and_gets_the_run_back(
    run_world: RunWorld,
) -> None:
    body = run_body(await run_world.basket(1))
    del body["seed"]
    user = uuid.uuid4()
    headers = {**quant(user), "Idempotency-Key": "noseed"}
    first = await run_world.client.post(RUNS, json=body, headers=headers)
    again = await run_world.client.post(RUNS, json=body, headers=headers)
    assert first.json()["id"] == again.json()["id"] and first.json()["seed"] == again.json()["seed"]


async def test_a_key_used_for_a_different_run_is_a_conflict(run_world: RunWorld) -> None:
    basket = await run_world.basket(2)
    user = uuid.uuid4()
    headers = {**quant(user), "Idempotency-Key": "k2"}
    assert (
        await run_world.client.post(RUNS, json=run_body(basket), headers=headers)
    ).status_code == 202
    for override in ({"n_paths": 300}, {"seed": 8}, {"n_steps": 21}):
        changed = await run_world.client.post(
            RUNS, json=run_body(basket, **override), headers=headers
        )
        assert changed.status_code == 409, override
        assert changed.json()["type"] == "urn:quantsim:problem:idempotency-conflict"
    assert len(await run_world.sql("SELECT 1 FROM run")) == 1


async def test_two_callers_may_share_a_key_and_without_a_key_every_submit_is_its_own_run(
    run_world: RunWorld,
) -> None:
    body = run_body(await run_world.basket(1))
    headers = {"Idempotency-Key": "shared"}
    one = await run_world.client.post(RUNS, json=body, headers={**quant(uuid.uuid4()), **headers})
    two = await run_world.client.post(RUNS, json=body, headers={**quant(uuid.uuid4()), **headers})
    assert one.json()["id"] != two.json()["id"]
    assert (await submit(run_world, body))["id"] != (await submit(run_world, body))["id"]


async def test_simultaneous_submits_with_one_key_make_one_run(run_world: RunWorld) -> None:
    body = run_body(await run_world.basket(1))
    user = uuid.uuid4()
    answers = await asyncio.gather(
        *[
            run_world.client.post(
                RUNS, json=body, headers={**quant(user), "Idempotency-Key": "burst"}
            )
            for _ in range(6)
        ]
    )
    assert {a.status_code for a in answers} == {202} and len({a.json()["id"] for a in answers}) == 1
    assert len(await run_world.sql("SELECT 1 FROM run")) == 1


async def test_a_hundred_submits_stay_under_800_ms_at_the_95th_percentile(
    run_world: RunWorld,
) -> None:
    body = run_body(await run_world.basket(3), n_paths=20, n_steps=1)
    times: list[float] = []
    for _ in range(100):
        began = time.perf_counter()
        response = await run_world.client.post(RUNS, json=body, headers=quant())
        times.append(time.perf_counter() - began)
        assert response.status_code == 202
    assert float(np.percentile(times, 95)) < 0.8, f"p95 {np.percentile(times, 95):.3f}s"
    assert len(await run_world.sql("SELECT 1 FROM job")) == 100


# ---- reproducibility (B-NFR-05) ----


async def test_the_same_seed_gives_the_same_statistics_and_the_same_stored_paths(
    run_world: RunWorld,
) -> None:
    basket = await run_world.basket(3)
    first = await complete(run_world, run_body(basket, n_paths=300))
    second = await complete(run_world, run_body(basket, n_paths=300))
    assert first["id"] != second["id"]
    assert first["statistics"] == second["statistics"]
    assert first["median_path_index"] == second["median_path_index"]
    assert await fingerprint_of_paths(run_world, first["id"]) == await fingerprint_of_paths(
        run_world, second["id"]
    )
    other = await complete(run_world, run_body(basket, n_paths=300, seed=8))
    assert other["statistics"] != first["statistics"]


async def test_one_two_and_four_worker_processes_give_identical_runs(run_world: RunWorld) -> None:
    basket = await run_world.basket(2)
    results = []
    for workers in (1, 2, 4):
        settings = run_world.settings.model_copy(update={"shard_workers": workers})
        deps = Dependencies(
            run_world.source, run_world.correlations, run_world.calibrator, run_world.risk
        )
        worker = Worker(
            run_world.database,
            run_world.queue,
            build_handlers(settings, run_world.database, deps),
            worker_id=f"w{workers}",
        )
        queued = await submit(run_world, run_body(basket, n_paths=1000, n_steps=10))
        assert await worker.run_once()
        done = await poll(run_world, queued["id"])
        assert done["status"] == "completed"
        results.append(
            (
                done["statistics"],
                done["median_path_index"],
                await fingerprint_of_paths(run_world, done["id"]),
            )
        )
    assert results[0] == results[1] == results[2]


async def test_a_job_that_dies_before_it_writes_leaves_nothing_and_its_rerun_is_identical(
    run_world: RunWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    basket = await run_world.basket(2)
    clean = await complete(run_world, run_body(basket, n_paths=300))
    real_copy = runs_module._copy
    failures = {"left": 1}

    async def dying_copy(*args: Any, **kwargs: Any) -> None:
        if failures["left"]:
            failures["left"] -= 1
            raise RuntimeError("the worker was killed while writing")
        await real_copy(*args, **kwargs)

    monkeypatch.setattr(runs_module, "_copy", dying_copy)
    queued = await submit(run_world, run_body(basket, n_paths=300))
    assert await run_world.worker.run_once()  # first attempt: dies after generating, before commit
    half = await poll(run_world, queued["id"])
    assert half["status"] == "running" and half["statistics"] == []
    for table in (
        "run_instrument",
        "run_statistics",
        "run_correlation",
        "path_quantile",
        "path_value",
    ):
        assert await count(run_world, table, queued["id"]) == 0, table
    assert await run_world.events("sim.completed", queued["id"]) == []
    await run_world.run_jobs()  # the queue runs it again
    again = await poll(run_world, queued["id"])
    assert again["status"] == "completed" and again["statistics"] == clean["statistics"]
    assert again["median_path_index"] == clean["median_path_index"]
    assert await fingerprint_of_paths(run_world, again["id"]) == await fingerprint_of_paths(
        run_world, clean["id"]
    )
    assert len(await run_world.events("sim.completed", queued["id"])) == 1


async def test_a_run_whose_job_is_run_again_after_it_completed_does_not_write_twice(
    run_world: RunWorld,
) -> None:
    done = await complete(run_world, run_body(await run_world.basket(2)))
    [state] = await run_world.sql("SELECT payload FROM job WHERE id = :i", i=uuid.UUID(done["id"]))
    handler = build_handlers(
        run_world.settings,
        run_world.database,
        Dependencies(
            run_world.source, run_world.correlations, run_world.calibrator, run_world.risk
        ),
    )["monte_carlo"]
    from qs_template.jobs import Job

    async def ignore(_: float) -> None:
        return None

    job = Job(uuid.UUID(done["id"]), "monte_carlo", state.payload, 2, "k")
    assert await handler(job, ignore) == {"status": "completed"}
    assert len(await run_world.events("sim.completed", done["id"])) == 1
    assert await count(run_world, "run_statistics", done["id"]) == 2


# ---- the storage rule through the pipeline (DL-013, ADR 03) ----


async def test_a_run_at_the_limit_is_stored_in_full(run_world: RunWorld) -> None:
    basket = await run_world.basket(1)
    done = await complete(run_world, run_body(basket, n_paths=1000, n_steps=252))
    assert done["storage_mode"] == "full"
    assert await count(run_world, "path_value", done["id"]) == 252_000
    assert await count(run_world, "path_quantile", done["id"]) == 252


async def test_a_larger_run_stores_the_seed_and_the_quantiles_but_no_paths(
    run_world: RunWorld,
) -> None:
    done = await complete(run_world, run_body(await run_world.basket(1), n_paths=600, n_steps=500))
    assert done["storage_mode"] == "quantiles" and done["status"] == "completed"
    assert await count(run_world, "path_value", done["id"]) == 0
    assert await count(run_world, "path_quantile", done["id"]) == 500
    assert 0 <= done["median_path_index"] < 600  # the path is still chosen: it regenerates


async def test_more_than_ten_instruments_is_stored_as_quantiles_whatever_the_size(
    run_world: RunWorld,
) -> None:
    done = await complete(run_world, run_body(await run_world.basket(11), n_paths=20, n_steps=5))
    assert done["storage_mode"] == "quantiles" and len(done["statistics"]) == 11
    assert await count(run_world, "path_value", done["id"]) == 0
    assert await count(run_world, "path_quantile", done["id"]) == 5 * 11


# ---- a stored path regenerates bit for bit (B-FR-14) ----


async def stored_paths(
    w: RunWorld, run_id: str, instruments: int, n_paths: int, steps: int
) -> np.ndarray:
    rows = await w.sql(
        "SELECT instrument_id, path_index, step, price FROM path_value WHERE run_id = :r",
        r=uuid.UUID(run_id),
    )
    order = {
        r.instrument_id: r.position
        for r in await w.sql(
            "SELECT instrument_id, position FROM run_instrument WHERE run_id = :r",
            r=uuid.UUID(run_id),
        )
    }
    grid = np.empty((n_paths, steps, instruments), dtype=object)
    for r in rows:
        grid[r.path_index, r.step - 1, order[r.instrument_id]] = r.price
    return grid


@pytest.mark.parametrize("model", ["gbm", "ou", "merton"])
async def test_a_regenerated_path_equals_the_stored_one_bit_for_bit(
    run_world: RunWorld, model: str
) -> None:
    basket = await run_world.basket(2, model=model)
    done = await complete(run_world, run_body(basket, model=model, n_paths=520, n_steps=12))
    stored = await stored_paths(run_world, done["id"], 2, 520, 12)
    async with run_world.database.transaction() as session:
        paths, _ = await regenerate(session, uuid.UUID(done["id"]))
    assert paths.shape == (520, 12, 2)  # three shards: the join between them is covered
    again = np.vectorize(to_price, otypes=[object])(paths)
    assert (again == stored).all()


async def test_a_run_whose_matrix_needed_repair_regenerates_exactly_and_records_the_repair(
    run_world: RunWorld,
) -> None:
    run_world.correlations.full = np.array(
        [[1.0, 0.9, -0.9], [0.9, 1.0, 0.9], [-0.9, 0.9, 1.0]]
    )  # not positive semi-definite
    basket = await run_world.basket(3)
    done = await complete(run_world, run_body(basket, n_paths=300, n_steps=10))
    assert done["status"] == "completed"
    [corr] = await run_world.sql(
        "SELECT * FROM run_correlation WHERE run_id = :r", r=uuid.UUID(done["id"])
    )
    assert corr.repair_applied is True and float(corr.min_eigenvalue_before) < 0
    assert float(corr.frobenius_change) > 0
    assert np.array(corr.matrix)[0, 2] == -0.9  # the matrix as given, before repair
    stored = await stored_paths(run_world, done["id"], 3, 300, 10)
    async with run_world.database.transaction() as session:
        paths, record = await regenerate(session, uuid.UUID(done["id"]))
    assert record.applied and (np.vectorize(to_price, otypes=[object])(paths) == stored).all()


async def test_a_run_kept_as_quantiles_regenerates_to_its_stored_quantiles(
    run_world: RunWorld,
) -> None:
    done = await complete(run_world, run_body(await run_world.basket(1), n_paths=600, n_steps=500))
    async with run_world.database.transaction() as session:
        paths, _ = await regenerate(session, uuid.UUID(done["id"]))
    expected = np.quantile(paths[:, :, 0], [0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99], axis=0)
    rows = await run_world.sql(
        "SELECT step, q01, q05, q25, q50, q75, q95, q99 FROM path_quantile"
        " WHERE run_id = :r ORDER BY step",
        r=uuid.UUID(done["id"]),
    )
    assert len(rows) == 500
    for row in rows:
        assert [float(v) for v in row[1:]] == pytest.approx(expected[:, row.step - 1], abs=1e-9)


async def test_a_run_that_is_not_complete_cannot_be_regenerated(run_world: RunWorld) -> None:
    queued = await submit(run_world, run_body(await run_world.basket(1)))
    from qs_template.errors import ServiceError

    async with run_world.database.transaction() as session:
        with pytest.raises(ServiceError) as refused:
            await regenerate(session, uuid.UUID(queued["id"]))
    assert refused.value.status == 409
    async with run_world.database.transaction() as session:
        with pytest.raises(ServiceError) as unknown:
            await regenerate(session, uuid.uuid4())
    assert unknown.value.status == 404


# ---- the statistics are the risk formula's (B-FR-13) ----


async def test_var_and_cvar_equal_the_formula_on_the_stored_terminal_prices(
    run_world: RunWorld,
) -> None:
    from qs_simulation.adapters.risk import reference_var_cvar

    basket = await run_world.basket(2)
    done = await complete(run_world, run_body(basket, n_paths=400, n_steps=30))
    stored = await stored_paths(run_world, done["id"], 2, 400, 30)
    for position, stat in enumerate(done["statistics"]):
        [row] = await run_world.sql(
            "SELECT s0 FROM run_instrument WHERE run_id = :r AND position = :p",
            r=uuid.UUID(done["id"]),
            p=position,
        )
        terminal = np.array([float(p) for p in stored[:, -1, position]])
        var, cvar = reference_var_cvar(terminal / float(row.s0) - 1.0)
        assert float(stat["var95"]) == pytest.approx(var, abs=1e-9)
        assert float(stat["cvar95"]) == pytest.approx(cvar, abs=1e-9)
        assert float(stat["var95"]) <= float(stat["cvar95"])


# ---- what the job refuses (the run is marked failed, and nothing is stored) ----


async def failed(w: RunWorld, body: dict[str, Any]) -> dict[str, Any]:
    done = await complete(w, body)
    assert done["status"] == "failed", done
    for table in ("run_instrument", "run_statistics", "path_quantile", "path_value"):
        assert await count(w, table, done["id"]) == 0, table
    [event] = await w.events("sim.failed", done["id"])
    assert event["data"]["reason"] in done["error"]
    return done


async def test_a_correlation_that_was_not_computed_refuses_the_run_naming_the_pair(
    run_world: RunWorld,
) -> None:
    run_world.correlations.unavailable = (("AAPL0", "MSFT1", "constant_series"),)
    run_world.correlations.full = np.array([[1.0, np.nan], [np.nan, 1.0]])
    done = await failed(run_world, run_body(await run_world.basket(2)))
    assert (
        "AAPL0" in done["error"] and "MSFT1" in done["error"] and "constant_series" in done["error"]
    )
    assert done["error"].startswith("correlation_unavailable:")
    assert run_world.correlations.calls == 1  # a refusal is not retried


async def test_a_matrix_with_undefined_cells_that_are_not_listed_is_refused_too(
    run_world: RunWorld,
) -> None:
    run_world.correlations.full = np.array([[1.0, np.nan], [np.nan, 1.0]])
    done = await failed(run_world, run_body(await run_world.basket(2)))
    assert "undefined" in done["error"]


async def test_a_matrix_the_generator_cannot_take_is_refused(run_world: RunWorld) -> None:
    run_world.correlations.full = np.array([[1.0, 1.5], [1.5, 1.0]])
    done = await failed(run_world, run_body(await run_world.basket(2)))
    assert done["error"].startswith("invalid_correlation:")


async def test_an_instrument_without_a_recent_close_has_no_start_price(
    run_world: RunWorld,
) -> None:
    basket = await run_world.basket(1)
    async with run_world.database.transaction() as session:
        await session.execute(
            text("UPDATE calibration SET window_end = window_end + 90, window_start = window_start")
        )
    done = await failed(run_world, run_body(basket))
    assert done["error"].startswith("no_start_price:")


async def test_an_instrument_the_market_service_does_not_know_refuses_the_run(
    run_world: RunWorld,
) -> None:
    basket = await run_world.basket(2)
    del run_world.source.points[basket[1][0]]
    done = await failed(run_world, run_body(basket))
    assert done["error"].startswith("instrument_not_found:")


async def test_paths_that_cannot_be_stored_refuse_the_run_instead_of_failing_in_the_database(
    run_world: RunWorld,
) -> None:
    basket = await run_world.basket(1)
    async with run_world.database.transaction() as session:
        await session.execute(
            text("""UPDATE calibration SET params = '{"mu": 5000.0, "sigma": 0.2}'""")
        )
    done = await failed(run_world, run_body(basket, n_steps=200))
    assert done["error"].startswith("unstorable_paths:")


# ---- a service that is down (B-NFR-10, this side) ----


async def test_a_correlation_service_that_fails_once_is_retried_and_the_run_completes(
    run_world: RunWorld,
) -> None:
    run_world.correlations.failures = 1
    queued = await submit(run_world, run_body(await run_world.basket(2)))
    assert await run_world.run_jobs() == 2
    assert (await poll(run_world, queued["id"]))["status"] == "completed"
    assert run_world.correlations.calls == 2


async def test_a_price_source_that_stays_down_ends_in_a_failed_run_with_the_error(
    run_world: RunWorld,
) -> None:
    run_world.source.failures = 99
    queued = await submit(run_world, run_body(await run_world.basket(2)))
    assert await run_world.run_jobs() == 3  # the queue's attempts, then it gives up
    done = await poll(run_world, queued["id"])
    assert done["status"] == "failed" and "not answering" in done["error"]
    assert len(await run_world.events("sim.failed", queued["id"])) == 1
    assert await run_world.events("sim.completed", queued["id"]) == []


# ---- reading a run, and who may do what ----


async def test_a_queued_run_names_its_instruments_before_anything_is_generated(
    run_world: RunWorld,
) -> None:
    basket = await run_world.basket(3)
    queued = await submit(run_world, run_body(basket))
    assert queued["symbols"] == ["AAPL0", "MSFT1", "NVDA2"] and queued["status"] == "queued"
    assert (await poll(run_world, queued["id"]))["symbols"] == queued["symbols"]


async def test_only_quants_and_admins_launch_and_everyone_signed_in_reads(
    run_world: RunWorld,
) -> None:
    body = run_body(await run_world.basket(2))
    for role in (Role.VIEWER, Role.ANALYST):
        denied = await run_world.client.post(RUNS, json=body, headers=bearer(make_token(role)))
        assert denied.status_code == 403, role
    made = []
    for role in (Role.QUANT, Role.ADMIN):
        accepted = await run_world.client.post(RUNS, json=body, headers=bearer(make_token(role)))
        assert accepted.status_code == 202, role
        made.append(accepted.json()["id"])
    for role in Role:
        read = await run_world.client.get(f"{RUNS}/{made[0]}", headers=bearer(make_token(role)))
        assert read.status_code == 200, role
    for headers in ({}, bearer(make_token(Role.ADMIN, forged=True))):
        assert (await run_world.client.post(RUNS, json=body, headers=headers)).status_code == 401
        assert (await run_world.client.get(f"{RUNS}/{made[0]}", headers=headers)).status_code == 401
    assert len(await run_world.sql("SELECT 1 FROM run")) == 2  # the refused callers made nothing


async def test_an_unknown_run_is_404_and_a_bad_id_is_422(run_world: RunWorld) -> None:
    viewer = bearer(make_token(Role.VIEWER))
    assert (await run_world.client.get(f"{RUNS}/{uuid.uuid4()}", headers=viewer)).status_code == 404
    assert (await run_world.client.get(f"{RUNS}/nope", headers=viewer)).status_code == 422


async def test_the_routes_the_read_api_builds_later_still_say_so(run_world: RunWorld) -> None:
    viewer = bearer(make_token(Role.VIEWER))
    assert (await run_world.client.get(RUNS, headers=viewer)).status_code == 501
    ticks = await run_world.client.get(f"{RUNS}/{uuid.uuid4()}/ticks", headers=viewer)
    assert ticks.status_code == 501


async def test_the_run_creation_is_in_the_openapi_document(run_world: RunWorld) -> None:
    spec = (await run_world.client.get("/api/simulation/openapi.json")).json()
    post = spec["paths"]["/api/simulation/runs"]["post"]
    assert "202" in post["responses"] and post["tags"] == ["runs"]
    assert "Idempotency-Key" in {p["name"] for p in post["parameters"]}
    assert spec["components"]["schemas"]["RunCreate"]["examples"][0]["n_paths"] == 1000


async def test_without_price_and_correlation_sources_the_route_says_so(
    migrated_database_url: str,
) -> None:
    from fakeredis import FakeAsyncRedis
    from pydantic import SecretStr

    from qs_simulation.main import build_app
    from qs_simulation.settings import SimulationSettings
    from qs_template import Database
    from qs_template.auth import Authenticator, StaticKeys
    from qs_template.revocation import RevocationList
    from tests.auth_support import _jwks

    settings = SimulationSettings(
        database_url=SecretStr(migrated_database_url),
        redis_url=SecretStr("redis://unused"),
        auth_jwks_url="http://127.0.0.1:1/jwks.json",
        content_hash="test-hash",
    )
    database = Database(settings)
    app = build_app(
        settings,
        database=database,
        revocations=RevocationList(FakeAsyncRedis()),
        authenticator=Authenticator(settings, jwks=StaticKeys(_jwks())),
    )
    body = {
        "model": "gbm",
        "instruments": [{"instrument_id": str(uuid.uuid4()), "calibration_id": str(uuid.uuid4())}],
        "n_paths": 100,
        "n_steps": 10,
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://simulation"
    ) as http:
        response = await http.post(RUNS, json=body, headers=quant())
    assert response.status_code == 503
    assert response.json()["type"] == "urn:quantsim:problem:simulation-unavailable"
    await database.close()
