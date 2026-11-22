"""Calibration against the real K5 fitting code (B-FR-08, B-FR-09): the stored fit is what K5 gives
for the same window, a refusal carries K5's own reason, and Merton, which waited for K5, works."""

from decimal import Decimal
from typing import Any

import numpy as np
import pytest
from qs_quant.calibration import fit_gbm, fit_merton, fit_ou

from qs_simulation.domain.calibration import PricePoint, log_prices, log_returns
from tests.calibration_support import (
    AAPL,
    DT,
    START,
    World,
    make_points,
    request_body,
)
from tests.test_calibrations import calibrate

pytestmark = pytest.mark.db


def with_closes(closes: np.ndarray) -> list[PricePoint]:
    """Consecutive weekdays with these adjusted closes."""
    days = make_points(len(closes), start=START)
    return [
        PricePoint(day.session_date, Decimal(f"{close:.10f}"), 1)
        for day, close in zip(days, closes, strict=True)
    ]


def mean_reverting(n: int, *, seed: int = 3) -> list[PricePoint]:
    """An Ornstein-Uhlenbeck log price (kappa 8, long-run level 4.6, sigma 0.3)."""
    rng = np.random.default_rng(seed)
    kappa, theta, sigma = 8.0, 4.6, 0.3
    decay = float(np.exp(-kappa * DT))
    sd = sigma * float(np.sqrt((1 - decay**2) / (2 * kappa)))
    level = np.empty(n)
    level[0] = theta
    for i in range(1, n):
        level[i] = theta + (level[i - 1] - theta) * decay + sd * rng.normal()
    return with_closes(np.exp(level))


def jumpy(n: int, *, seed: int = 5) -> list[PricePoint]:
    """Daily returns with occasional large jumps."""
    rng = np.random.default_rng(seed)
    shocks = rng.normal(0.0004, 0.01, size=n)
    shocks += (rng.random(n) < 0.02) * rng.normal(-0.03, 0.04, size=n)
    return with_closes(100.0 * np.exp(np.cumsum(shocks)))


async def test_the_stored_gbm_fit_equals_a_direct_k5_call(k5_world: World) -> None:
    points = make_points(300)
    k5_world.source.add(AAPL, points)
    done = await calibrate(k5_world)
    assert done["status"] == "succeeded", done
    stored: dict[str, Any] = done["calibration"]
    direct = fit_gbm(log_returns(points), DT)
    assert stored["params"] == pytest.approx(direct.params, abs=1e-12)
    assert stored["std_errors"] == pytest.approx(direct.std_errors, abs=1e-12)
    assert float(stored["aic"]) == pytest.approx(direct.aic, abs=1e-9)
    assert stored["n_obs"] == direct.n_obs == 299
    assert stored["qs_quant_version"] not in ("unavailable", "unknown")


async def test_ou_on_a_random_walk_is_refused_with_k5s_own_reason(k5_world: World) -> None:
    k5_world.source.add(AAPL, make_points(400, seed=11))
    done = await calibrate(k5_world, request_body(model="ou"))
    assert done["status"] == "refused", done
    assert done["refusal"]["http_status"] == 422
    assert done["refusal"]["reason"].startswith("not_mean_reverting")


async def test_ou_on_a_mean_reverting_series_is_stored_as_k5_fitted_it(k5_world: World) -> None:
    points = mean_reverting(600)
    k5_world.source.add(AAPL, points)
    done = await calibrate(k5_world, request_body(model="ou"))
    assert done["status"] == "succeeded", done
    direct = fit_ou(log_prices(points), DT)
    assert not direct.refused
    assert set(done["calibration"]["params"]) == {"kappa", "theta", "sigma"}
    assert done["calibration"]["params"] == pytest.approx(direct.params, abs=1e-12)


async def test_merton_is_calibrated_now_that_k5_provides_it(k5_world: World) -> None:
    points = jumpy(700)
    k5_world.source.add(AAPL, points)
    done = await calibrate(k5_world, request_body(model="merton"))
    assert done["status"] == "succeeded", done
    direct = fit_merton(log_returns(points), DT)
    assert set(done["calibration"]["params"]) == {"mu", "sigma", "lam", "mu_j", "sigma_j"}
    assert done["calibration"]["params"] == pytest.approx(direct.params, abs=1e-9)


async def test_merton_on_a_short_window_is_refused_with_the_reason_k5_gave(
    k5_world: World,
) -> None:
    k5_world.source.add(AAPL, make_points(300))
    done = await calibrate(k5_world, request_body(model="merton"))
    assert done["status"] == "refused", done
    assert done["refusal"]["reason"].startswith("insufficient_history")
