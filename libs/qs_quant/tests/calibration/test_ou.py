"""OU against an exact OLS reference, the ADF refusal and the delta-method Jacobian
(C-FR-02, C-FR-04)."""

import json
import math
from fractions import Fraction
from pathlib import Path

import numpy as np
import pytest

from qs_quant.calibration import MIN_OBS_OU, fit_ou, refusal_code
from qs_quant.calibration.ou import ou_jacobian
from tests.calibration import simulate as sim

FIXTURE = json.loads(
    (Path(__file__).parents[1] / "fixtures" / "calibration_fixture.json").read_text(
        encoding="utf-8"
    )
)
LOG_PRICES = [float(v) for v in FIXTURE["ou_log_prices"]]
DT = 1 / 252
TOL = 1e-12


def close(got: float, expected: float, tol: float = TOL) -> bool:
    return math.isclose(got, expected, rel_tol=tol)


def test_fit_matches_exact_ols_and_the_transform() -> None:
    x = [Fraction(v) for v in LOG_PRICES]
    lag, y = x[:-1], x[1:]
    n = len(y)
    lag_mean = sum(lag, Fraction(0)) / n
    y_mean = sum(y, Fraction(0)) / n
    sxx = sum(((v - lag_mean) ** 2 for v in lag), Fraction(0))
    sxy = sum(((u - lag_mean) * (v - y_mean) for u, v in zip(lag, y, strict=True)), Fraction(0))
    b = sxy / sxx
    a = y_mean - b * lag_mean
    s2 = sum(((v - a - b * u) ** 2 for u, v in zip(lag, y, strict=True)), Fraction(0)) / n
    kappa = -math.log(float(b)) / DT
    theta = float(a / (1 - b))
    sigma = math.sqrt(float(s2)) * math.sqrt(2 * kappa / float(1 - b * b))
    log_likelihood = -(n / 2) * math.log(2 * math.pi * float(s2)) - n / 2

    fit = fit_ou(LOG_PRICES)
    assert fit.refusal_reason is None and fit.converged and fit.n_obs == n == 300
    assert close(fit.params["kappa"], kappa)
    assert close(fit.params["theta"], theta)
    assert close(fit.params["sigma"], sigma)
    assert close(fit.log_likelihood, log_likelihood)
    assert close(fit.aic, 6 - 2 * log_likelihood)
    assert all(v > 0 and math.isfinite(v) for v in fit.std_errors.values())


def test_the_jacobian_matches_central_differences() -> None:
    a, b, s, dt = 0.12, 0.97, 0.015, DT

    def transform(a: float, b: float, s: float) -> np.ndarray:
        kappa = -math.log(b) / dt
        return np.array([kappa, a / (1 - b), s * math.sqrt(2 * kappa / (1 - b * b))])

    numeric = np.empty((3, 3))
    for col, h in enumerate((1e-7, 1e-9, 1e-9)):
        step = np.zeros(3)
        step[col] = h
        numeric[:, col] = (
            transform(*(np.array([a, b, s]) + step)) - transform(*(np.array([a, b, s]) - step))
        ) / (2 * h)
    assert np.allclose(ou_jacobian(a, b, s, dt), numeric, rtol=1e-6, atol=1e-9)


def test_random_walks_are_refused_with_the_adf_p_value() -> None:
    # Guide §14: a random walk is refused in at least 90% of 50 seeds
    reasons = [
        fit_ou(sim.random_walk(np.random.default_rng(seed), 2_520)).refusal_reason
        for seed in range(50)
    ]
    refused = [r for r in reasons if r is not None]
    assert len(refused) >= 45, f"only {len(refused)}/50 random walks refused"
    assert all(r.startswith("not_mean_reverting: ") for r in refused)
    assert all("ADF p = " in r for r in refused if "ADF" in r)


def test_mean_reverting_series_are_accepted() -> None:
    accepted = sum(
        not fit_ou(sim.ou_log_prices(np.random.default_rng(seed), 2_520, **sim.OU_TRUE)).refused
        for seed in range(50)
    )
    assert accepted >= 45, f"only {accepted}/50 mean-reverting series accepted"


def test_the_refusal_reason_names_the_p_value() -> None:
    reason = fit_ou(sim.random_walk(np.random.default_rng(1), 2_520)).refusal_reason
    assert reason is not None
    assert reason.startswith("not_mean_reverting: series is not mean-reverting (ADF p = 0.")


def test_a_negative_ar1_slope_is_refused() -> None:
    # Strongly alternating around a level: ADF rejects a unit root, but b < 0
    g = np.random.default_rng(5)
    x = [4.6]
    for _ in range(400):
        x.append(4.6 - 0.8 * (x[-1] - 4.6) + 0.01 * g.standard_normal())
    fit = fit_ou(x)
    assert refusal_code(fit) == "not_mean_reverting"
    assert fit.refusal_reason is not None and "AR(1) coefficient b = -" in fit.refusal_reason


def test_the_minimum_history_is_sixty_transitions() -> None:
    short = fit_ou(LOG_PRICES[:MIN_OBS_OU])  # 59 transitions
    assert refusal_code(short) == "insufficient_history" and short.n_obs == 59


@pytest.mark.parametrize("bad", [[], [4.6] * 100, [math.nan] * 100, "abc"])
def test_bad_input_is_refused_not_raised(bad: object) -> None:
    fit = fit_ou(bad)  # type: ignore[arg-type]
    assert refusal_code(fit) in {"invalid_input", "insufficient_history", "constant_series"}


def test_determinism() -> None:
    assert fit_ou(LOG_PRICES) == fit_ou(np.array(LOG_PRICES))
