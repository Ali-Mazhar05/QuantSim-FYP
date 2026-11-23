"""Independent checks of the K5 maths (docs/report/k5-maths.md).

Each estimator is checked against a different method that must agree with it:

- GBM and OU: the estimate maximises the model's exact likelihood written directly in
  the model parameters, and the reported standard errors equal the inverse observed
  information of that likelihood (a numerical Hessian), not just the formulas the code
  uses.
- OU: a general-purpose optimiser on the exact transition density finds the same
  estimate as the closed-form OLS route.
- Merton: the truncated mixture density integrates to one and has the analytic mean and
  variance of a jump diffusion step; the fitted point is a local maximum.
"""

import math
from collections.abc import Callable

import numpy as np
from numpy.typing import NDArray
from scipy.optimize import minimize

from qs_quant.calibration import fit_gbm, fit_merton, fit_ou
from qs_quant.calibration.merton import PARAMS, log_density, neg_log_likelihood
from tests.calibration import simulate as sim

DT = 1 / 252
Vector = NDArray[np.float64]


def hessian(f: Callable[[Vector], float], x: Vector, rel: float = 1e-4) -> Vector:
    """Central-difference Hessian of f at x, written out independently of the library."""
    k = x.size
    h = rel * np.maximum(1.0, np.abs(x))
    out = np.empty((k, k))
    for i in range(k):
        for j in range(k):
            ei, ej = np.zeros(k), np.zeros(k)
            ei[i], ej[j] = h[i], h[j]
            out[i, j] = (f(x + ei + ej) - f(x + ei - ej) - f(x - ei + ej) + f(x - ei - ej)) / (
                4 * h[i] * h[j]
            )
    return out


def inverse_information_se(f: Callable[[Vector], float], x: Vector) -> Vector:
    return np.sqrt(np.diag(np.linalg.inv(hessian(f, x))))


# GBM ------------------------------------------------------------------------------------


def gbm_nll(r: Vector) -> Callable[[Vector], float]:
    def f(theta: Vector) -> float:
        mu, sigma = theta
        mean, var = (mu - sigma**2 / 2) * DT, sigma**2 * DT
        return float(0.5 * np.sum(np.log(2 * math.pi * var) + (r - mean) ** 2 / var))

    return f


def test_gbm_estimate_maximises_the_exact_likelihood_with_matching_errors() -> None:
    r = sim.gbm_log_returns(sim.rng("maths-gbm", 0), 2_520, **sim.GBM_TRUE)
    fit = fit_gbm(r)
    x = np.array([fit.params["mu"], fit.params["sigma"]])
    f = gbm_nll(r)
    # The reported log L is the exact likelihood at the estimate
    assert math.isclose(f(x), -fit.log_likelihood, rel_tol=1e-12)
    # No direction improves it: a general optimiser started elsewhere returns the same point
    other = minimize(
        f,
        x * np.array([0.5, 1.3]),
        method="Nelder-Mead",
        options={"xatol": 1e-10, "fatol": 1e-10, "maxiter": 20_000},
    )
    assert np.allclose(other.x, x, rtol=1e-5)
    # Standard errors equal the inverse observed information
    se = inverse_information_se(f, x)
    assert math.isclose(fit.std_errors["sigma"], se[1], rel_tol=1e-4)
    # se(mu) neglects the sigma^2/2 term: the exact one is sqrt(sigma^2/(n dt) + sigma^4/(2n)),
    # larger by a factor sqrt(1 + sigma^2 dt / 2), about 4e-5 here
    n, sigma = r.size, x[1]
    assert math.isclose(se[0], math.sqrt(sigma**2 / (n * DT) + sigma**4 / (2 * n)), rel_tol=1e-4)
    assert math.isclose(fit.std_errors["mu"], se[0], rel_tol=1e-3)


# OU -------------------------------------------------------------------------------------


def ou_nll(x: Vector) -> Callable[[Vector], float]:
    """-log L of the exact OU transition density, in the model parameters."""

    def f(theta: Vector) -> float:
        kappa, level, sigma = theta
        if kappa <= 0 or sigma <= 0:
            return 1e300
        b = math.exp(-kappa * DT)
        mean = level + (x[:-1] - level) * b
        var = sigma**2 * (-math.expm1(-2 * kappa * DT)) / (2 * kappa)
        return float(0.5 * np.sum(np.log(2 * math.pi * var) + (x[1:] - mean) ** 2 / var))

    return f


def test_ou_ols_route_is_the_exact_maximum_likelihood_estimate() -> None:
    x = sim.ou_log_prices(sim.rng("maths-ou", 0), 2_520, **sim.OU_TRUE)
    fit = fit_ou(x)
    assert fit.refusal_reason is None
    est = np.array([fit.params["kappa"], fit.params["theta"], fit.params["sigma"]])
    f = ou_nll(x)
    # The conditional AR(1) likelihood is the exact transition likelihood, reparametrised
    assert math.isclose(f(est), -fit.log_likelihood, rel_tol=1e-10)
    # An optimiser on the exact density, from a distant start, lands on the OLS estimate
    other = minimize(
        f,
        np.array([1.0, est[1] + 0.05, 0.6]),
        method="Nelder-Mead",
        options={"xatol": 1e-10, "fatol": 1e-10, "maxiter": 50_000},
    )
    assert np.allclose(other.x, est, rtol=1e-5)


def test_ou_delta_method_errors_equal_the_inverse_observed_information() -> None:
    # At the MLE, a smooth reparametrisation transforms the information as J' I J, so the
    # delta method is exact here up to finite-difference error
    x = sim.ou_log_prices(sim.rng("maths-ou", 1), 2_520, **sim.OU_TRUE)
    fit = fit_ou(x)
    est = np.array([fit.params["kappa"], fit.params["theta"], fit.params["sigma"]])
    se = inverse_information_se(ou_nll(x), est)
    for name, value in zip(("kappa", "theta", "sigma"), se, strict=True):
        assert math.isclose(fit.std_errors[name], float(value), rel_tol=1e-3), name


# Merton ---------------------------------------------------------------------------------


def test_merton_density_integrates_to_one_with_the_analytic_moments() -> None:
    mu, sigma, lam, mu_j, sigma_j = 0.05, 0.15, 10.0, -0.03, 0.04
    theta = np.array([mu, sigma, lam, mu_j, sigma_j])
    grid = np.linspace(-1.0, 1.0, 400_001)
    jumps = np.arange(11, dtype=np.float64)
    log_factorials = np.array([math.lgamma(j + 1) for j in jumps])
    f = np.exp(log_density(theta, grid, DT, jumps, log_factorials))
    mass = float(np.trapezoid(f, grid))
    mean = float(np.trapezoid(grid * f, grid))
    var = float(np.trapezoid((grid - mean) ** 2 * f, grid))
    kbar = math.expm1(mu_j + sigma_j**2 / 2)
    # One step: diffusion plus a compound Poisson sum of N(mu_j, sigma_j^2) jumps
    expected_mean = (mu - sigma**2 / 2 - lam * kbar) * DT + lam * DT * mu_j
    expected_var = sigma**2 * DT + lam * DT * (sigma_j**2 + mu_j**2)
    # Truncating at 10 jumps drops P(N > 10) ~ (lam dt)^11 / 11!, about 1e-23
    assert math.isclose(mass, 1.0, rel_tol=1e-9)
    assert math.isclose(mean, expected_mean, rel_tol=1e-7, abs_tol=1e-12)
    assert math.isclose(var, expected_var, rel_tol=1e-7)


def test_merton_likelihood_sums_the_density() -> None:
    r = sim.merton_log_returns(sim.rng("maths-merton", 0), 600, **sim.MERTON_TRUE)
    theta = np.array(list(sim.MERTON_TRUE.values()))
    jumps = np.arange(11, dtype=np.float64)
    log_factorials = np.array([math.lgamma(j + 1) for j in jumps])
    total = float(np.sum(log_density(theta, r, DT, jumps, log_factorials)))
    assert math.isclose(neg_log_likelihood(theta, r, DT, jumps, log_factorials), -total)


def test_merton_fit_is_a_local_maximum() -> None:
    r = sim.merton_log_returns(sim.rng("maths-merton", 1), 2_520, **sim.MERTON_TRUE)
    fit = fit_merton(r)
    assert fit.refusal_reason is None and fit.converged
    best = np.array([fit.params[name] for name in PARAMS])
    jumps = np.arange(11, dtype=np.float64)
    log_factorials = np.array([math.lgamma(j + 1) for j in jumps])
    at_best = neg_log_likelihood(best, r, DT, jumps, log_factorials)
    assert math.isclose(at_best, -fit.log_likelihood)
    # A step of one standard error either way along any parameter lowers log L
    for i, name in enumerate(PARAMS):
        for sign in (-1.0, 1.0):
            moved = best.copy()
            moved[i] += sign * fit.std_errors[name]
            assert neg_log_likelihood(moved, r, DT, jumps, log_factorials) > at_best, name
