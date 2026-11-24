"""Calibration end to end (B15, B-FR-08, B-FR-09, B-NFR-09, B-NFR-10): the real routes, the real job
queue and worker and a migrated database, around a price source and a calibrator it controls."""

import asyncio
import math
import time
import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from qs_simulation.calibrations import KIND, make_handler
from qs_simulation.domain.calibration import FitResult, PricePoint, input_fingerprint
from qs_simulation.ports import CalibratorUnavailable
from qs_template.auth import Role
from qs_template.jobs import Job
from tests.auth_support import bearer, make_token
from tests.calibration_support import (
    AAPL,
    CALIBRATIONS,
    World,
    make_points,
    reference_gbm,
    request_body,
)

pytestmark = pytest.mark.db

SAME_USER = uuid.uuid4()
NOT_MEAN_REVERTING = "series is not mean-reverting (ADF p = 0.41)"


def quant(user: uuid.UUID | None = None) -> dict[str, str]:
    return bearer(make_token(Role.QUANT, user_id=user))


async def submit(w: World, body: dict[str, Any] | None = None, **headers: str) -> dict[str, Any]:
    response = await w.client.post(
        CALIBRATIONS, json=body or request_body(), headers={**quant(), **headers}
    )
    assert response.status_code == 202, response.text
    result: dict[str, Any] = response.json()
    return result


async def poll(w: World, calibration_id: str) -> dict[str, Any]:
    response = await w.client.get(
        f"{CALIBRATIONS}/{calibration_id}", headers=bearer(make_token(Role.VIEWER))
    )
    assert response.status_code == 200, response.text
    result: dict[str, Any] = response.json()
    return result


async def calibrate(w: World, body: dict[str, Any] | None = None) -> dict[str, Any]:
    queued = await submit(w, body)
    assert await w.run_jobs() >= 1
    return await poll(w, queued["id"])


@pytest.fixture
def prices(world: World) -> list[Any]:
    points = make_points(300)
    world.source.add(AAPL, points)
    return points


# ---- the fit is stored as the model returned it (B-FR-08) ----


async def test_the_stored_fit_equals_a_direct_call_on_the_same_window(
    world: World, prices: list[Any]
) -> None:
    done = await calibrate(world)
    assert done["status"] == "succeeded" and done["progress"] == 1.0
    stored = done["calibration"]
    direct = reference_gbm(prices)
    assert stored["params"] == direct.params
    assert stored["std_errors"] == direct.std_errors
    assert float(stored["log_likelihood"]) == pytest.approx(direct.log_likelihood, abs=1e-9)
    assert float(stored["aic"]) == pytest.approx(direct.aic, abs=1e-9)
    assert (stored["n_obs"], stored["converged"]) == (direct.n_obs, True)
    assert stored["model"] == "gbm" and stored["symbol"] == "AAPL"
    assert stored["instrument_id"] == str(AAPL)
    assert (stored["window_start"], stored["window_end"]) == ("2020-01-01", "2021-12-31")
    assert stored["qs_quant_version"] == "reference-0.1"
    assert stored["input_fingerprint"] == input_fingerprint(prices)
    assert world.calibrator.calls == [("gbm", 300)]


async def test_the_window_bounds_choose_the_sessions_that_are_fitted(
    world: World, prices: list[Any]
) -> None:
    first, last = prices[40], prices[199]
    done = await calibrate(
        world,
        request_body(
            window_start=first.session_date.isoformat(), window_end=last.session_date.isoformat()
        ),
    )
    assert done["calibration"]["n_obs"] == 159  # 160 sessions, 159 returns
    assert done["calibration"]["input_fingerprint"] == input_fingerprint(prices[40:200])


async def test_the_symbol_of_the_instrument_is_remembered_for_the_pages(
    world: World, prices: list[Any]
) -> None:
    await calibrate(world)
    async with world.database.transaction() as session:
        row = (await session.execute(text("SELECT symbol, name FROM instrument_ref"))).one()
    assert (row.symbol, row.name) == ("AAPL", "Apple Inc.")


async def test_recalibrating_unchanged_data_reproduces_the_fingerprint_and_the_fit(
    world: World, prices: list[Any]
) -> None:
    first = await calibrate(world)
    second = await calibrate(world)
    assert first["id"] != second["id"]  # a new calibration each time: the history is kept
    one, two = first["calibration"], second["calibration"]
    assert one["input_fingerprint"] == two["input_fingerprint"]
    assert (one["params"], one["std_errors"], one["aic"]) == (
        two["params"],
        two["std_errors"],
        two["aic"],
    )


async def test_a_restated_close_changes_the_fingerprint(world: World, prices: list[Any]) -> None:
    before = await calibrate(world)
    spoiled = [*prices[:100], PricePoint(prices[100].session_date, prices[100].adj_close * 2, 1)]
    world.source.add(AAPL, spoiled + prices[101:])
    after = await calibrate(world)
    assert after["calibration"]["input_fingerprint"] != before["calibration"]["input_fingerprint"]


# ---- what is refused, and why (B-FR-09) ----


async def test_fifty_nine_sessions_are_refused_before_any_model_is_asked(
    world: World,
) -> None:
    world.source.add(AAPL, make_points(59))
    done = await calibrate(world)
    assert done["status"] == "refused" and done["calibration"] is None
    assert done["refusal"]["http_status"] == 422
    assert done["refusal"]["code"] == "insufficient_history"
    assert "59 sessions" in done["refusal"]["reason"]
    assert world.calibrator.calls == []  # K5 was never called


async def test_sixty_sessions_reach_the_model_which_may_still_say_no(world: World) -> None:
    # 60 sessions pass the history check; they are 59 returns, and the fit needs 60 of those, so
    # the model refuses in its own words rather than the service guessing
    world.source.add(AAPL, make_points(60))
    done = await calibrate(world)
    assert done["status"] == "refused" and done["refusal"]["code"] == "fit_refused"
    assert world.calibrator.calls == [("gbm", 60)]


async def test_sixty_one_sessions_are_the_fewest_a_fit_is_stored_for(world: World) -> None:
    world.source.add(AAPL, make_points(61))
    done = await calibrate(world)
    assert done["status"] == "succeeded" and done["calibration"]["n_obs"] == 60


async def test_ou_on_a_random_walk_is_refused_with_the_reason_the_model_gave(
    world: World, prices: list[Any]
) -> None:
    world.calibrator.scripted["ou"] = FitResult(
        "ou", {}, {}, 0.0, 0.0, 299, False, NOT_MEAN_REVERTING
    )
    done = await calibrate(world, request_body(model="ou"))
    assert done["status"] == "refused"
    assert done["refusal"] == {
        "http_status": 422,
        "code": "fit_refused",
        "reason": NOT_MEAN_REVERTING,
    }
    assert world.calibrator.calls == [("ou", 300)]
    async with world.database.transaction() as session:
        assert (await session.execute(text("SELECT count(*) FROM calibration"))).scalar_one() == 0


@pytest.mark.parametrize(
    ("fit", "fragment"),
    [
        (FitResult("gbm", {"mu": math.nan, "sigma": 0.2}, {}, 1.0, 1.0, 100, True), "not finite"),
        (FitResult("gbm", {"mu": 0.1, "sigma": 0.2}, {}, math.inf, 1.0, 100, True), "not finite"),
        (FitResult("gbm", {"mu": 0.1, "sigma": 0.2}, {}, 1.0, math.nan, 100, True), "AIC"),
        (FitResult("gbm", {"mu": 0.1, "sigma": 0.2}, {}, 1.0, 1.0, 59, True), "59 observations"),
    ],
)
async def test_a_fit_that_cannot_be_stored_is_refused_not_stored(
    world: World, prices: list[Any], fit: FitResult, fragment: str
) -> None:
    world.calibrator.scripted["gbm"] = fit
    done = await calibrate(world)
    assert done["status"] == "refused" and fragment in done["refusal"]["reason"]
    assert done["refusal"]["code"] == "fit_refused"


async def test_an_unknown_instrument_is_refused_with_its_own_code(
    world: World,
) -> None:
    done = await calibrate(world)  # the source knows no instrument
    assert done["status"] == "refused" and done["refusal"]["code"] == "instrument_not_found"


async def test_a_close_that_is_not_positive_is_refused(world: World, prices: list[Any]) -> None:
    bad = PricePoint(prices[50].session_date, prices[50].adj_close * 0, 1)
    world.source.add(AAPL, [*prices[:50], bad, *prices[51:]])
    done = await calibrate(world)
    assert done["refusal"]["code"] == "invalid_prices"
    assert prices[50].session_date.isoformat() in done["refusal"]["reason"]


async def test_a_standard_error_the_model_could_not_compute_is_stored_as_null(
    world: World, prices: list[Any]
) -> None:
    world.calibrator.scripted["gbm"] = FitResult(
        "gbm", {"mu": 0.1, "sigma": 0.2}, {"mu": math.nan, "sigma": 0.01}, -5.5, 15.0, 299, True
    )
    done = await calibrate(world)
    assert done["calibration"]["std_errors"] == {"mu": None, "sigma": 0.01}
    assert done["calibration"]["converged"] is True


# ---- a price source that is down (B-NFR-10, fault injection on this side) ----


async def test_a_price_source_that_fails_once_is_retried_and_the_calibration_is_made(
    world: World, prices: list[Any]
) -> None:
    world.source.failures = 1
    queued = await submit(world)
    assert await world.run_jobs() == 2  # the first attempt failed, the second worked
    done = await poll(world, queued["id"])
    assert done["status"] == "succeeded" and world.source.calls == 2


async def test_a_price_source_that_stays_down_ends_in_a_failed_job_with_the_error(
    world: World, prices: list[Any]
) -> None:
    world.source.failures = 99
    queued = await submit(world)
    assert await world.run_jobs() == 3  # the queue's attempts, then it gives up
    done = await poll(world, queued["id"])
    assert done["status"] == "failed" and done["calibration"] is None
    assert "not answering" in done["error"] and done["refusal"] is None
    assert world.source.calls == 3
    assert not await world.worker.run_once()  # nothing is left to run


async def test_a_job_run_again_after_a_crash_keeps_the_one_calibration(
    world: World, prices: list[Any]
) -> None:
    queued = await submit(world)
    handler = make_handler(
        database=world.database, source=world.source, calibrator=world.calibrator
    )
    job = Job(
        id=uuid.UUID(queued["id"]),
        kind=KIND,
        payload={
            **request_body(),
            "created_by": str(uuid.uuid4()),
        },
        attempt=1,
        idempotency_key="k",
    )

    async def ignore(_: float) -> None:
        return None

    first = await handler(job, ignore)
    again = await handler(job, ignore)  # the worker died before it could record the result
    assert first == again == {"status": "succeeded", "calibration_id": queued["id"]}
    async with world.database.transaction() as session:
        assert (await session.execute(text("SELECT count(*) FROM calibration"))).scalar_one() == 1


# ---- the route ----


async def test_a_submit_answers_202_at_once_with_the_id_to_poll(
    world: World, prices: list[Any]
) -> None:
    began = time.perf_counter()
    response = await world.client.post(CALIBRATIONS, json=request_body(), headers=quant())
    elapsed = time.perf_counter() - began
    assert response.status_code == 202 and elapsed < 0.8, f"{elapsed:.2f}s"
    body = response.json()
    assert response.headers["Location"] == f"/api/simulation/calibrations/{body['id']}"
    assert body["status"] == "queued" and body["calibration"] is None and body["progress"] == 0
    assert world.calibrator.calls == [] and world.source.calls == 0  # nothing ran in the request
    again = await poll(world, body["id"])
    assert again["status"] == "queued"
    await world.run_jobs()
    assert (await poll(world, body["id"]))["status"] == "succeeded"


async def test_the_same_idempotency_key_returns_the_same_calibration(
    world: World, prices: list[Any]
) -> None:
    first = await world.client.post(
        CALIBRATIONS,
        json=request_body(),
        headers={**quant(SAME_USER), "Idempotency-Key": "retry-1"},
    )
    second = await world.client.post(
        CALIBRATIONS,
        json=request_body(),
        headers={**quant(SAME_USER), "Idempotency-Key": "retry-1"},
    )
    assert first.status_code == second.status_code == 202
    assert first.json()["id"] == second.json()["id"]
    await world.run_jobs()
    third = await world.client.post(
        CALIBRATIONS,
        json=request_body(),
        headers={**quant(SAME_USER), "Idempotency-Key": "retry-1"},
    )
    assert third.json()["id"] == first.json()["id"] and third.json()["status"] == "succeeded"
    async with world.database.transaction() as session:
        assert (await session.execute(text("SELECT count(*) FROM calibration"))).scalar_one() == 1
        assert (await session.execute(text("SELECT count(*) FROM job"))).scalar_one() == 1


async def test_two_callers_may_use_the_same_key_without_meeting(
    world: World, prices: list[Any]
) -> None:
    keyed = {"Idempotency-Key": "shared"}
    one = await world.client.post(
        CALIBRATIONS,
        json=request_body(),
        headers={**bearer(make_token(Role.QUANT, user_id=uuid.uuid4())), **keyed},
    )
    two = await world.client.post(
        CALIBRATIONS,
        json=request_body(),
        headers={**bearer(make_token(Role.QUANT, user_id=uuid.uuid4())), **keyed},
    )
    assert one.json()["id"] != two.json()["id"]


async def test_without_a_key_every_submit_is_its_own_calibration(
    world: World, prices: list[Any]
) -> None:
    assert (await submit(world))["id"] != (await submit(world))["id"]


async def test_simultaneous_submits_with_one_key_make_one_job(
    world: World, prices: list[Any]
) -> None:
    answers = await asyncio.gather(
        *[
            world.client.post(
                CALIBRATIONS,
                json=request_body(),
                headers={**quant(SAME_USER), "Idempotency-Key": "burst"},
            )
            for _ in range(5)
        ]
    )
    assert {a.status_code for a in answers} == {202}
    assert len({a.json()["id"] for a in answers}) == 1


@pytest.mark.parametrize(
    "override",
    [
        {"model": "garch"},
        {"window_start": "2021-12-31", "window_end": "2020-01-01"},
        {"window_start": "2020-06-01", "window_end": "2020-06-01"},
        {"instrument_id": "not-a-uuid"},
        {"window_end": "soon"},
    ],
)
async def test_a_bad_request_is_422_and_queues_nothing(
    world: World, override: dict[str, Any]
) -> None:
    response = await world.client.post(CALIBRATIONS, json=request_body(**override), headers=quant())
    assert response.status_code == 422, override
    async with world.database.transaction() as session:
        assert (await session.execute(text("SELECT count(*) FROM job"))).scalar_one() == 0


async def test_a_missing_field_is_422(world: World) -> None:
    body = request_body()
    del body["model"]
    response = await world.client.post(CALIBRATIONS, json=body, headers=quant())
    assert response.status_code == 422


async def test_merton_is_501_until_the_fitting_code_exists(world: World) -> None:
    response = await world.client.post(
        CALIBRATIONS, json=request_body(model="merton"), headers=quant()
    )
    assert response.status_code == 501
    assert response.json()["type"] == "urn:quantsim:problem:not-implemented"
    assert not world.calibrator.supports("merton")
    with pytest.raises(CalibratorUnavailable):
        world.calibrator.fit("merton", make_points(600))


# ---- who may do what ----


async def test_only_quants_and_admins_calibrate_and_everyone_signed_in_reads(
    world: World, prices: list[Any]
) -> None:
    for role in (Role.VIEWER, Role.ANALYST):
        denied = await world.client.post(
            CALIBRATIONS, json=request_body(), headers=bearer(make_token(role))
        )
        assert denied.status_code == 403, role
    made: list[str] = []
    for role in (Role.QUANT, Role.ADMIN):
        accepted = await world.client.post(
            CALIBRATIONS, json=request_body(), headers=bearer(make_token(role))
        )
        assert accepted.status_code == 202, role
        made.append(accepted.json()["id"])
    for role in Role:
        read = await world.client.get(f"{CALIBRATIONS}/{made[0]}", headers=bearer(make_token(role)))
        assert read.status_code == 200, role
    for headers in ({}, bearer(make_token(Role.ADMIN, forged=True))):
        assert (
            await world.client.post(CALIBRATIONS, json=request_body(), headers=headers)
        ).status_code == 401
        assert (
            await world.client.get(f"{CALIBRATIONS}/{made[0]}", headers=headers)
        ).status_code == 401
    async with world.database.transaction() as session:
        assert (await session.execute(text("SELECT count(*) FROM job"))).scalar_one() == 2


async def test_an_unknown_calibration_is_404_and_a_bad_id_is_422(
    world: World,
) -> None:
    viewer = bearer(make_token(Role.VIEWER))
    assert (
        await world.client.get(f"{CALIBRATIONS}/{uuid.uuid4()}", headers=viewer)
    ).status_code == 404
    assert (await world.client.get(f"{CALIBRATIONS}/nope", headers=viewer)).status_code == 422


async def test_a_job_of_another_kind_is_not_a_calibration(
    world: World,
) -> None:
    async with world.database.transaction() as session:
        other = await world.queue.submit(session, "monte_carlo", {"n": 1})
    response = await world.client.get(
        f"{CALIBRATIONS}/{other.id}", headers=bearer(make_token(Role.VIEWER))
    )
    assert response.status_code == 404


async def test_the_database_holds_a_calibration_only_with_enough_observations(
    world: World, prices: list[Any]
) -> None:
    done = await calibrate(world)
    assert done["status"] == "succeeded"
    with pytest.raises(DBAPIError, match="calibration_enough_observations"):
        async with world.database.transaction() as session:
            await session.execute(text("UPDATE calibration SET n_obs = 59"))


# ---- the service without a price source ----


async def test_without_a_price_source_the_route_says_so_instead_of_queueing_work_nobody_does(
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
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://simulation"
    ) as http:
        response = await http.post(CALIBRATIONS, json=request_body(), headers=quant())
    assert response.status_code == 503
    assert response.json()["type"] == "urn:quantsim:problem:calibration-unavailable"
    await database.close()
