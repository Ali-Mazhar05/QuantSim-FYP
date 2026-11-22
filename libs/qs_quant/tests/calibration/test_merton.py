"""Merton: refusals, the objective's edge cases, bounds and stability (C-FR-03, C-NFR-02)."""

import math

import numpy as np
import pytest

from qs_quant.calibration import MIN_OBS_MERTON, fit_merton, refusal_code
from qs_quant.calibration.merton import BOUNDS, PARAMS, _standard_errors, neg_log_likelihood
from tests.calibration import simulate as sim


def sample(n: int, seed: int = 11) -> np.ndarray:
    return sim.merton_log_returns(np.random.default_rng(seed), n, **sim.MERTON_TRUE)


def same(a: float, b: float) -> bool:
    return (math.isnan(a) and math.isnan(b)) or a == b


def test_the_minimum_history_is_five_hundred_returns() -> None:
    returns = sample(MIN_OBS_MERTON)
    short = fit_merton(returns[:-1])
    assert refusal_code(short) == "insufficient_history"
    assert (
        short.refusal_reason
        == "insufficient_history: Merton needs at least 500 observations, got 499"
    )
    assert not fit_merton(returns, n_starts=1).refused


def test_a_fit_returns_every_parameter_inside_its_bounds() -> None:
    fit = fit_merton(sample(2_520))
    assert fit.refusal_reason is None
    assert list(fit.params) == list(PARAMS) == list(fit.std_errors)
    for name, (lo, hi) in zip(PARAMS, BOUNDS, strict=True):
        assert lo <= fit.params[name] <= hi, name
    assert fit.converged
    assert math.isclose(fit.aic, 10 - 2 * fit.log_likelihood)


@pytest.mark.parametrize(
    "options", [{"n_starts": 0}, {"n_starts": 4}, {"max_jumps": 0}, {"max_jumps": 2.5}]
)
def test_bad_options_are_refused(options: dict[str, float]) -> None:
    assert refusal_code(fit_merton(sample(600), **options)) == "invalid_input"  # type: ignore[arg-type]


def test_a_constant_or_invalid_series_is_refused() -> None:
    assert refusal_code(fit_merton([0.0] * 600)) == "constant_series"
    assert refusal_code(fit_merton([math.nan] * 600)) == "invalid_input"


def test_the_objective_handles_no_jumps_and_penalises_the_impossible() -> None:
    r = sample(600)
    jumps = np.arange(11, dtype=np.float64)
    log_factorials = np.array([math.lgamma(j + 1) for j in jumps])
    no_jumps = neg_log_likelihood(
        np.array([0.05, 0.15, 0.0, 0.0, 0.02]), r, 1 / 252, jumps, log_factorials
    )
    assert math.isfinite(no_jumps)
    # lam = 0 is exactly GBM: -log L equals the Gaussian one with (mu - sigma^2/2) dt mean
    mean, var = (0.05 - 0.15**2 / 2) / 252, 0.15**2 / 252
    gaussian = 0.5 * np.sum(np.log(2 * math.pi * var) + (r - mean) ** 2 / var)
    assert math.isclose(no_jumps, float(gaussian), rel_tol=1e-12)
    impossible = neg_log_likelihood(
        np.array([0.0, 0.0, 0.0, 0.0, 0.0]), r, 1 / 252, jumps, log_factorials
    )
    assert impossible == 1e300


def test_a_parameter_on_a_bound_gets_a_nan_standard_error() -> None:
    # A quadratic bowl with its minimum at a point whose lam sits on the lower bound
    centre = np.array([0.05, 0.15, 0.0, -0.03, 0.04])

    def bowl(theta: np.ndarray) -> float:
        return float(np.sum(((theta - centre) / np.array([0.1, 0.01, 1.0, 0.01, 0.01])) ** 2) / 2)

    se = _standard_errors(centre, bowl)
    assert math.isnan(se[2])
    # The others: H = diag(1 / scale^2), so SE = scale
    assert np.allclose(se[[0, 1, 3, 4]], [0.1, 0.01, 0.01, 0.01], rtol=1e-4)


def test_a_hessian_that_is_not_positive_definite_gives_nan_errors() -> None:
    saddle = np.array([0.05, 0.15, 5.0, -0.03, 0.04])
    se = _standard_errors(saddle, lambda t: float(-np.sum((t - saddle) ** 2)))
    assert all(math.isnan(v) for v in se)


def test_extreme_returns_stay_finite() -> None:
    # C-NFR-02: ten years of daily data with +-50% days, no NaN, overflow or warning
    r = sample(2_520, seed=3)
    r[::250] = np.log(1.5)
    r[125::250] = np.log(0.5)
    fit = fit_merton(r, n_starts=1)
    assert fit.refusal_reason is None
    assert math.isfinite(fit.log_likelihood)


def test_determinism() -> None:
    r = sample(800, seed=2)
    a, b = fit_merton(r, n_starts=2), fit_merton(r.copy(), n_starts=2)
    assert a.params == b.params and a.log_likelihood == b.log_likelihood
    assert all(same(a.std_errors[k], b.std_errors[k]) for k in PARAMS)
