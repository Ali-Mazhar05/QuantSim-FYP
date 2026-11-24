"""Stress scenarios (B17, B-FR-15, B-FR-16): the maths of the two overlays, then the stressed run
end to end: the parent is not changed, the stressed run is stored and served like any run, and a
scenario inserted as a row works with no code change."""

import uuid
from decimal import Decimal
from typing import Any

import httpx
import numpy as np
import pytest

from qs_simulation.domain.generators import simulate_gbm, simulate_merton, simulate_ou
from qs_simulation.domain.scenarios import (
    PriceShock,
    Scenario,
    VolMultiplier,
    apply_prices,
    parse,
    price_factors,
    vol_scale,
)
from qs_simulation.domain.sharding import PathRequest, generate
from qs_template.auth import Role
from tests.auth_support import bearer, make_token
from tests.run_support import RUNS, RunWorld, run_body
from tests.test_runs import complete, fingerprint_of_paths, poll

DT = 1 / 252
SCENARIOS = "/api/simulation/scenarios"


def shock(drop: float, at_step: int, recovery: int = 0) -> Scenario:
    return Scenario(
        "price_shock", shock=PriceShock(drop=drop, at_step=at_step, recovery_steps=recovery)
    )


def spike(multiplier: float, start: int, end: int) -> Scenario:
    return Scenario(
        "vol_multiplier", vol=VolMultiplier(multiplier=multiplier, from_step=start, to_step=end)
    )


def request(
    model: str, scenario: Scenario | None, n_paths: int = 400, n_steps: int = 30
) -> PathRequest:
    params = {
        "gbm": {"mu": np.array([0.1, 0.05]), "sigma": np.array([0.25, 0.4])},
        "ou": {
            "kappa": np.array([4.0, 6.0]),
            "theta": np.array([4.6, 4.0]),
            "sigma": np.array([0.3, 0.5]),
        },
        "merton": {
            "mu": np.array([0.1, 0.05]),
            "sigma": np.array([0.2, 0.3]),
            "lam": np.array([20.0, 10.0]),
            "mu_j": np.array([-0.02, -0.01]),
            "sigma_j": np.array([0.05, 0.04]),
        },
    }[model]
    return PathRequest(
        model=model,  # type: ignore[arg-type]
        s0=np.array([100.0, 55.0]),
        params=params,
        correlation=np.array([[1.0, 0.5], [0.5, 1.0]]),
        n_paths=n_paths,
        n_steps=n_steps,
        seed=11,
        scenario=scenario,
    )


# ---- the maths ----


def test_a_price_shock_multiplies_every_price_from_its_step_and_nothing_before() -> None:
    base, _ = generate(request("gbm", None), 1)
    hit, _ = generate(request("gbm", shock(0.25, 10)), 1)
    assert np.array_equal(hit[:, :9, :], base[:, :9, :])  # steps 1 to 9 are the parent's
    assert np.allclose(hit[:, 9:, :], base[:, 9:, :] * 0.75, rtol=1e-12, atol=0)
    mean_ratio = hit[:, -1, :].mean(axis=0) / base[:, -1, :].mean(axis=0)
    assert mean_ratio == pytest.approx([0.75, 0.75], rel=1e-12)  # the analytical effect


def test_a_shock_heals_in_a_straight_line_over_its_recovery_steps() -> None:
    factors = price_factors(shock(0.4, 5, recovery=4), 12)
    assert factors is not None
    assert factors.tolist() == pytest.approx([1, 1, 1, 1, 0.6, 0.7, 0.8, 0.9, 1, 1, 1, 1])
    permanent = price_factors(shock(0.4, 5), 8)
    assert permanent is not None and permanent.tolist() == pytest.approx([1] * 4 + [0.6] * 4)
    assert price_factors(None, 5) is None and price_factors(spike(2, 1, 2), 5) is None


def test_applying_a_shock_leaves_its_input_alone() -> None:
    paths = np.full((3, 6, 2), 10.0)
    stressed = apply_prices(shock(0.5, 2), paths)
    assert (paths == 10.0).all() and stressed[0, 1, 0] == 5.0
    assert apply_prices(None, paths) is paths


def test_the_volatility_scale_marks_exactly_the_stressed_steps() -> None:
    scale = vol_scale(spike(3, 4, 6), 8)
    assert scale is not None and scale.tolist() == [1, 1, 1, 3, 3, 3, 1, 1]
    assert vol_scale(None, 4) is None and vol_scale(shock(0.1, 2), 4) is None


@pytest.mark.parametrize("model", ["gbm", "ou", "merton"])
def test_a_spike_changes_only_the_stressed_steps_and_the_rest_are_the_parents_shocks(
    model: str,
) -> None:
    base, _ = generate(request(model, None), 1)
    hot, _ = generate(request(model, spike(3, 11, 20)), 1)
    log_base, log_hot = np.log(base), np.log(hot)
    one = np.zeros((base.shape[0], 1, base.shape[2]))
    step_base = np.diff(log_base, axis=1, prepend=one)
    step_hot = np.diff(log_hot, axis=1, prepend=one)
    # before the window the paths are the same bit for bit, so the shocks are the same too
    assert np.array_equal(hot[:, :10, :], base[:, :10, :])
    assert not np.allclose(step_hot[:, 10:20, :], step_base[:, 10:20, :])
    assert np.all(np.isfinite(hot))


def test_a_spike_scales_the_gbm_volatility_by_exactly_the_multiplier() -> None:
    n_paths, n_steps, n = 30_000, 40, 1
    shocks = np.random.default_rng(3).standard_normal((n_paths, n_steps, n))
    s0, mu, sigma = np.array([100.0]), np.array([0.08]), np.array([0.3])
    scale = vol_scale(spike(3, 11, 25), n_steps)
    stressed = np.diff(np.log(simulate_gbm(s0, mu, sigma, DT, shocks, scale)), axis=1)
    inside, outside = stressed[:, 10:24, 0], stressed[:, 30:, 0]

    assert inside.std() == pytest.approx(3 * 0.3 * np.sqrt(DT), rel=0.02)
    assert outside.std() == pytest.approx(0.3 * np.sqrt(DT), rel=0.02)
    # the Ito correction follows the stressed sigma, not the calibrated one
    expected = (0.08 - 0.5 * (3 * 0.3) ** 2) * DT
    assert abs(inside.mean() - expected) < 3 * inside.std() / np.sqrt(inside.size) + 1e-9


def test_a_spike_scales_the_ou_noise_by_exactly_the_multiplier() -> None:
    shocks = np.random.default_rng(4).standard_normal((50, 30, 1))
    args = (np.array([100.0]), np.array([5.0]), np.array([4.6]), np.array([0.3]), DT, shocks)
    base, hot = simulate_ou(*args), simulate_ou(*args, vol_scale(spike(4, 8, 14), 30))

    def noise(paths: Any) -> Any:
        x = np.log(paths)[:, :, 0]
        previous = np.concatenate([np.full((50, 1), np.log(100.0)), x[:, :-1]], axis=1)
        return x - 4.6 - (previous - 4.6) * np.exp(-5.0 * DT)

    ratio = noise(hot)[:, 7:14] / noise(base)[:, 7:14]
    assert ratio == pytest.approx(4.0, rel=1e-6)
    assert noise(hot)[:, 14:] / noise(base)[:, 14:] == pytest.approx(1.0, rel=1e-6)


def test_a_scale_of_ones_changes_nothing() -> None:
    shocks = np.random.default_rng(5).standard_normal((20, 12, 2))
    s0, mu, sigma = np.array([10.0, 20.0]), np.array([0.1, 0.0]), np.array([0.2, 0.3])
    ones = np.ones(12)
    assert np.array_equal(
        simulate_gbm(s0, mu, sigma, DT, shocks), simulate_gbm(s0, mu, sigma, DT, shocks, ones)
    )
    counts = np.random.default_rng(6).poisson(0.05, size=shocks.shape)
    jumps = np.random.default_rng(7).standard_normal(shocks.shape)
    merton = (s0, mu, sigma, np.array([5.0, 5.0]), np.array([-0.02, 0.0]), np.array([0.05, 0.05]))
    assert np.array_equal(
        simulate_merton(*merton, DT, shocks, counts, jumps),
        simulate_merton(*merton, DT, shocks, counts, jumps, ones),
    )


def test_a_scale_that_does_not_fit_is_refused_by_the_generator() -> None:
    shocks = np.zeros((2, 5, 1))
    args = (np.array([1.0]), np.array([0.0]), np.array([0.2]), DT, shocks)
    for bad in (np.ones(4), np.array([1, 1, 0, 1, 1.0]), np.array([1, 1, np.nan, 1, 1.0])):
        with pytest.raises(ValueError, match="vol_scale"):
            simulate_gbm(*args, bad)


@pytest.mark.parametrize(
    ("kind", "params", "fields"),
    [
        ("price_shock", {"drop": 1.5, "at_step": 3}, {"drop"}),
        ("price_shock", {"drop": 0.2, "at_step": 0}, {"at_step"}),
        ("price_shock", {"drop": 0, "at_step": 0}, {"drop", "at_step"}),
        ("price_shock", {"drop": 0.2}, {"at_step"}),
        ("price_shock", {"drop": 0.2, "at_step": 3, "colour": "red"}, {"colour"}),
        ("vol_multiplier", {"multiplier": 11, "from_step": 1, "to_step": 5}, {"multiplier"}),
        ("vol_multiplier", {"multiplier": 2, "from_step": 6, "to_step": 5}, set()),
    ],
)
def test_bad_parameters_are_named(kind: str, params: dict[str, Any], fields: set[str]) -> None:
    from pydantic import ValidationError

    from qs_simulation.domain.scenarios import problems_of

    with pytest.raises(ValidationError) as caught:
        parse(kind, params)
    named = {field for field, _ in problems_of(caught.value)}
    assert fields <= named and named


# ---- through the service ----


QUANT = uuid.uuid4()  # one caller: an idempotency key is scoped to the caller


def quant() -> dict[str, str]:
    return bearer(make_token(Role.QUANT, user_id=QUANT))


async def make_scenario(
    w: RunWorld, code: str, type_: str, params: dict[str, Any]
) -> httpx.Response:
    return await w.client.post(
        SCENARIOS,
        json={"code": code, "name": f"{code} scenario", "type": type_, "params": params},
        headers=quant(),
    )


async def stress(w: RunWorld, run_id: str, code: str, **headers: str) -> httpx.Response:
    return await w.client.post(
        f"{RUNS}/{run_id}/scenarios", json={"scenario": code}, headers={**quant(), **headers}
    )


async def stressed(w: RunWorld, run_id: str, code: str) -> dict[str, Any]:
    response = await stress(w, run_id, code)
    assert response.status_code == 202, response.text
    await w.run_jobs()
    return await poll(w, response.json()["id"])


async def ticks(w: RunWorld, run_id: str, path: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    after = 0
    while True:
        page = (
            await w.client.get(
                f"{RUNS}/{run_id}/ticks",
                params={"path": path, "after_seq": after, "limit": 500},
                headers=quant(),
            )
        ).json()
        out += page["items"]
        if page["next_after_seq"] is None:
            return out
        after = page["next_after_seq"]


@pytest.mark.db
async def test_a_scenario_is_added_listed_and_refused_when_it_is_wrong(run_world: RunWorld) -> None:
    made = await make_scenario(run_world, "crash_a", "price_shock", {"drop": 0.3, "at_step": 4})
    assert made.status_code == 201, made.text
    assert made.json()["code"] == "crash_a" and made.json()["params"]["drop"] == 0.3
    listed = (await run_world.client.get(SCENARIOS, headers=bearer(make_token(Role.VIEWER)))).json()
    assert [s["code"] for s in listed] == ["crash_a"]
    again = await make_scenario(run_world, "crash_a", "price_shock", {"drop": 0.1, "at_step": 4})
    assert again.status_code == 409
    wrong = await make_scenario(run_world, "bad_one", "price_shock", {"drop": 2, "at_step": 0})
    assert wrong.status_code == 422
    assert {e["field"] for e in wrong.json()["errors"]} == {"drop", "at_step"}
    assert "drop" in wrong.json()["detail"] and "at_step" in wrong.json()["detail"]
    odd = await run_world.client.post(
        SCENARIOS,
        json={"code": "x", "name": "x", "type": "price_shock", "params": {}},
        headers=quant(),
    )
    assert odd.status_code == 422  # the code does not fit the pattern: the request is refused
    for role in (Role.VIEWER, Role.ANALYST):
        refused = await run_world.client.post(
            SCENARIOS,
            json={
                "code": "crash_b",
                "name": "b",
                "type": "price_shock",
                "params": {"drop": 0.1, "at_step": 2},
            },
            headers=bearer(make_token(role)),
        )
        assert refused.status_code == 403
    assert (await run_world.client.get(SCENARIOS)).status_code == 401


@pytest.mark.db
async def test_a_stressed_run_leaves_its_parent_exactly_as_it_was(run_world: RunWorld) -> None:
    basket = await run_world.basket(2)
    base = await complete(run_world, run_body(basket, n_paths=120, n_steps=12))
    await make_scenario(run_world, "crash_a", "price_shock", {"drop": 0.3, "at_step": 4})
    before = (
        await fingerprint_of_paths(run_world, base["id"]),
        await run_world.sql(
            "SELECT * FROM path_quantile WHERE run_id = :r ORDER BY 1,2,3", r=uuid.UUID(base["id"])
        ),
        await run_world.sql(
            "SELECT * FROM run_statistics WHERE run_id = :r ORDER BY 2", r=uuid.UUID(base["id"])
        ),
        await run_world.sql(
            "SELECT status, median_path_index, seed FROM run WHERE id = :r", r=uuid.UUID(base["id"])
        ),
    )
    derived = await stressed(run_world, base["id"], "crash_a")
    assert derived["status"] == "completed" and derived["progress"] == 1.0
    assert derived["parent_run_id"] == base["id"] and derived["scenario"] == "crash_a"
    assert (derived["model"], derived["n_paths"], derived["n_steps"], derived["seed"]) == (
        base["model"],
        base["n_paths"],
        base["n_steps"],
        base["seed"],
    )
    assert derived["symbols"] == base["symbols"] and derived["id"] != base["id"]
    after = (
        await fingerprint_of_paths(run_world, base["id"]),
        await run_world.sql(
            "SELECT * FROM path_quantile WHERE run_id = :r ORDER BY 1,2,3", r=uuid.UUID(base["id"])
        ),
        await run_world.sql(
            "SELECT * FROM run_statistics WHERE run_id = :r ORDER BY 2", r=uuid.UUID(base["id"])
        ),
        await run_world.sql(
            "SELECT status, median_path_index, seed FROM run WHERE id = :r", r=uuid.UUID(base["id"])
        ),
    )
    assert after == before  # byte for byte
    base_view = (await run_world.client.get(f"{RUNS}/{base['id']}", headers=quant())).json()
    assert base_view["parent_run_id"] is None and base_view["scenario"] is None
    assert base_view == base


@pytest.mark.db
async def test_the_stressed_ticks_are_the_parents_with_the_shock_on_top(
    run_world: RunWorld,
) -> None:
    basket = await run_world.basket(2)
    base = await complete(run_world, run_body(basket, n_paths=60, n_steps=10))
    await make_scenario(run_world, "crash_a", "price_shock", {"drop": 0.3, "at_step": 4})
    derived = await stressed(run_world, base["id"], "crash_a")
    parent_ticks, child_ticks = (
        await ticks(run_world, base["id"], 7),
        await ticks(run_world, derived["id"], 7),
    )
    assert len(parent_ticks) == len(child_ticks) == 20
    assert {t["scenario"] for t in child_ticks} == {"crash_a"} and {
        t["scenario"] for t in parent_ticks
    } == {None}
    assert {t["env_id"] for t in child_ticks} == {derived["id"]}
    assert child_ticks[0]["source_fingerprint"] != parent_ticks[0]["source_fingerprint"]
    for parent, child in zip(parent_ticks, child_ticks, strict=True):
        assert (parent["seq"], parent["session"], parent["symbol"], parent["ts"]) == (
            child["seq"],
            child["session"],
            child["symbol"],
            child["ts"],
        )
        step = parent["session"] + 1
        if step < 4:
            assert child["close"] == parent["close"]  # before the shock: the same text
        else:
            expected = Decimal(parent["close"]) * Decimal("0.7")
            assert abs(Decimal(child["close"]) - expected) <= Decimal("2E-10")
    # the stressed statistics fall by the shock too: the terminal mean is 30% lower
    for old, new in zip(base["statistics"], derived["statistics"], strict=True):
        assert float(new["mean_price"]) == pytest.approx(0.7 * float(old["mean_price"]), rel=1e-8)
    assert 0 <= derived["median_path_index"] < 60


@pytest.mark.db
async def test_a_flash_crash_inserted_as_a_row_works_with_no_code_change(
    run_world: RunWorld,
) -> None:
    basket = await run_world.basket(2)
    base = await complete(run_world, run_body(basket, n_paths=40, n_steps=8))
    await run_world.sql("SELECT 1")
    async with run_world.database.transaction() as session:
        from sqlalchemy import text

        await session.execute(
            text(
                "INSERT INTO scenario (code, name, type, params) VALUES ('crash_90', 'A 90% crash',"
                " 'price_shock', '{\"drop\": 0.9, \"at_step\": 2}'::jsonb)"
            )
        )
    derived = await stressed(run_world, base["id"], "crash_90")
    assert derived["status"] == "completed" and derived["scenario"] == "crash_90"
    last = (await ticks(run_world, derived["id"], 0))[-1]
    first_parent = (await ticks(run_world, base["id"], 0))[-1]
    assert float(last["close"]) == pytest.approx(0.1 * float(first_parent["close"]), rel=1e-8)


@pytest.mark.db
async def test_a_volatility_spike_run_is_stored_and_served(run_world: RunWorld) -> None:
    basket = await run_world.basket(2)
    base = await complete(run_world, run_body(basket, n_paths=300, n_steps=24))
    await make_scenario(
        run_world, "spike", "vol_multiplier", {"multiplier": 4, "from_step": 6, "to_step": 18}
    )
    derived = await stressed(run_world, base["id"], "spike")
    assert derived["status"] == "completed" and derived["scenario"] == "spike"

    def spread(run: dict[str, Any]) -> float:
        stats = run["statistics"][0]
        return float(stats["p95_price"]) - float(stats["p5_price"])

    assert spread(derived) > spread(base)  # more volatility, a wider fan
    early = [t for t in await ticks(run_world, derived["id"], 3) if t["session"] < 5]
    same = [t for t in await ticks(run_world, base["id"], 3) if t["session"] < 5]
    assert [t["close"] for t in early] == [t["close"] for t in same]  # until the spike begins


@pytest.mark.parametrize(
    ("kind", "params"),
    [
        ("price_shock", {"drop": 0.25, "at_step": 3, "recovery_steps": 4}),
        ("vol_multiplier", {"multiplier": 3, "from_step": 2, "to_step": 6}),
    ],
)
@pytest.mark.db
async def test_a_stressed_run_kept_as_quantiles_regenerates_to_the_same_ticks(
    run_world: RunWorld, kind: str, params: dict[str, Any]
) -> None:
    basket = await run_world.basket(2, model="ou" if kind == "vol_multiplier" else "gbm")
    model = "ou" if kind == "vol_multiplier" else "gbm"
    base = await complete(run_world, run_body(basket, model=model, n_paths=520, n_steps=8))
    await make_scenario(run_world, "s1", kind, params)
    derived = await stressed(run_world, base["id"], "s1")
    stored = {p: await ticks(run_world, derived["id"], p) for p in (0, 251, 252, 519)}
    await run_world.sql("SELECT 1")
    async with run_world.database.transaction() as session:
        from sqlalchemy import text

        await session.execute(
            text("UPDATE run SET storage_mode = 'quantiles' WHERE id = :r"),
            {"r": uuid.UUID(derived["id"])},
        )
    for path, expected in stored.items():
        assert await ticks(run_world, derived["id"], path) == expected


@pytest.mark.db
async def test_what_cannot_be_stressed_is_refused_with_the_reason(run_world: RunWorld) -> None:
    basket = await run_world.basket(2)
    base = await complete(run_world, run_body(basket, n_paths=30, n_steps=6))
    await make_scenario(run_world, "late", "price_shock", {"drop": 0.2, "at_step": 7})
    await make_scenario(
        run_world, "long", "vol_multiplier", {"multiplier": 2, "from_step": 2, "to_step": 9}
    )
    late = await stress(run_world, base["id"], "late")
    assert late.status_code == 422 and [e["field"] for e in late.json()["errors"]] == ["at_step"]
    long = await stress(run_world, base["id"], "long")
    assert long.status_code == 422 and [e["field"] for e in long.json()["errors"]] == ["to_step"]
    assert (await stress(run_world, base["id"], "nope")).status_code == 404
    assert (await stress(run_world, str(uuid.uuid4()), "late")).status_code == 404
    waiting = await run_world.client.post(RUNS, json=run_body(basket, seed=2), headers=quant())
    assert (await stress(run_world, waiting.json()["id"], "late")).status_code == 409
    assert (await run_world.sql("SELECT count(*) AS n FROM run"))[0].n == 2  # nothing was queued


@pytest.mark.db
async def test_who_may_stress_a_run_and_a_repeated_key_gives_the_same_run(
    run_world: RunWorld,
) -> None:
    basket = await run_world.basket(2)
    base = await complete(run_world, run_body(basket, n_paths=30, n_steps=6))
    await make_scenario(run_world, "c1", "price_shock", {"drop": 0.2, "at_step": 2})
    await make_scenario(run_world, "c2", "price_shock", {"drop": 0.4, "at_step": 2})
    for role in (Role.VIEWER, Role.ANALYST):
        refused = await run_world.client.post(
            f"{RUNS}/{base['id']}/scenarios",
            json={"scenario": "c1"},
            headers=bearer(make_token(role)),
        )
        assert refused.status_code == 403
    assert (
        await run_world.client.post(f"{RUNS}/{base['id']}/scenarios", json={"scenario": "c1"})
    ).status_code == 401
    one = await stress(run_world, base["id"], "c1", **{"Idempotency-Key": "k1"})
    two = await stress(run_world, base["id"], "c1", **{"Idempotency-Key": "k1"})
    assert one.status_code == two.status_code == 202 and one.json()["id"] == two.json()["id"]
    other = await stress(run_world, base["id"], "c2", **{"Idempotency-Key": "k1"})
    assert other.status_code == 409


@pytest.mark.db
async def test_stressed_runs_are_listed_beside_their_parent(run_world: RunWorld) -> None:
    basket = await run_world.basket(2)
    base = await complete(run_world, run_body(basket, n_paths=30, n_steps=6))
    await make_scenario(run_world, "c1", "price_shock", {"drop": 0.2, "at_step": 2})
    derived = await stressed(run_world, base["id"], "c1")
    items = (await run_world.client.get(RUNS, headers=quant())).json()["items"]
    row = next(r for r in items if r["id"] == derived["id"])
    assert (row["parent_run_id"], row["scenario"], row["status"]) == (base["id"], "c1", "completed")
    assert next(r for r in items if r["id"] == base["id"])["parent_run_id"] is None
