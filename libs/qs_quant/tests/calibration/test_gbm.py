"""GBM against an exact rational reference, and its refusals (C-FR-01, C-FR-04)."""

import json
import math
from fractions import Fraction
from pathlib import Path

import numpy as np

from qs_quant.calibration import MIN_OBS_GBM, fit_gbm, refusal_code

FIXTURE = json.loads(
    (Path(__file__).parents[1] / "fixtures" / "calibration_fixture.json").read_text(
        encoding="utf-8"
    )
)
RETURNS = [float(v) for v in FIXTURE["gbm_log_returns"]]
DT = 1 / 252
TOL = 1e-12


def close(got: float, expected: float) -> bool:
    return math.isclose(got, expected, rel_tol=TOL)


def test_fit_matches_the_exact_closed_form() -> None:
    exact = [Fraction(v) for v in RETURNS]  # floats convert to fractions exactly
    n = len(exact)
    m = sum(exact, Fraction(0)) / n
    s2 = sum(((v - m) ** 2 for v in exact), Fraction(0)) / n
    sigma = math.sqrt(s2 / Fraction(DT))
    mu = float(m / Fraction(DT)) + sigma**2 / 2
    log_likelihood = -(n / 2) * math.log(2 * math.pi * float(s2)) - n / 2

    fit = fit_gbm(RETURNS)
    assert fit.refusal_reason is None and fit.converged
    assert fit.n_obs == n == 80
    assert close(fit.params["sigma"], sigma)
    assert close(fit.params["mu"], mu)
    assert close(fit.std_errors["sigma"], sigma / math.sqrt(2 * n))
    assert close(fit.std_errors["mu"], sigma / math.sqrt(n * DT))
    assert close(fit.log_likelihood, log_likelihood)
    assert close(fit.aic, 4 - 2 * log_likelihood)


def test_the_minimum_history_is_sixty_returns() -> None:
    short = fit_gbm(RETURNS[: MIN_OBS_GBM - 1])
    assert refusal_code(short) == "insufficient_history"
    assert (
        short.refusal_reason == "insufficient_history: GBM needs at least 60 observations, got 59"
    )
    assert short.n_obs == 59
    assert not fit_gbm(RETURNS[:MIN_OBS_GBM]).refused


def test_a_constant_series_is_refused() -> None:
    assert refusal_code(fit_gbm([0.001] * 100)) == "constant_series"


def test_bad_input_is_refused_not_raised() -> None:
    for bad in ([math.nan] * 70, [math.inf] * 70, [[0.1, 0.2]] * 70, ["x"] * 70):
        assert refusal_code(fit_gbm(bad)) == "invalid_input", bad
    # An empty series is well formed, just too short
    assert refusal_code(fit_gbm([])) == "insufficient_history"
    for dt in (0.0, -1 / 252, 2.0, math.nan):
        assert refusal_code(fit_gbm(RETURNS, dt=dt)) == "invalid_input", dt


def test_a_refusal_has_no_estimates() -> None:
    fit = fit_gbm(RETURNS[:10])
    assert fit.refused and not fit.converged
    assert fit.params == {} and fit.std_errors == {}
    assert math.isnan(fit.log_likelihood) and math.isnan(fit.aic)


def test_numpy_input_and_determinism() -> None:
    a, b = fit_gbm(np.array(RETURNS)), fit_gbm(RETURNS)
    assert a == b
