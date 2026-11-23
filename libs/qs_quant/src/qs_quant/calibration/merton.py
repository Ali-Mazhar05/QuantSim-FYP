"""Merton jump-diffusion by bounded multi-start maximum likelihood (K5, C-FR-03; guide §7.4)."""

import math
from collections.abc import Callable

import numpy as np
from numpy.typing import NDArray
from scipy.optimize import minimize
from scipy.special import gammaln, logsumexp

from qs_quant._validation import Series
from qs_quant.calibration._common import guarded, prepare
from qs_quant.calibration.gbm import fit_gbm
from qs_quant.calibration.result import (
    REFUSAL_CONSTANT_SERIES,
    REFUSAL_INSUFFICIENT_HISTORY,
    REFUSAL_INVALID_INPUT,
    REFUSAL_NUMERICAL_FAILURE,
    FitResult,
    aic,
    refused,
)

__all__ = ["BOUNDS", "MIN_OBS_MERTON", "PARAMS", "fit_merton"]

MIN_OBS_MERTON = 500
"""The fewest log returns fit_merton accepts (shorter windows are unstable)."""
PARAMS = ("mu", "sigma", "lam", "mu_j", "sigma_j")
BOUNDS = ((-2.0, 2.0), (1e-4, 3.0), (0.0, 252.0), (-1.0, 1.0), (1e-4, 1.0))
"""Bounds of (mu, sigma, lam, mu_j, sigma_j)."""
ON_BOUND = 1e-6
"""A parameter this close to a bound gets a NaN standard error."""
_PENALTY = 1e300
"""The objective's value where the likelihood is not finite, so the optimiser backs off."""

Objective = Callable[[NDArray[np.float64]], float]


def fit_merton(
    log_returns: Series, dt: float = 1 / 252, n_starts: int = 3, max_jumps: int = 10
) -> FitResult:
    """Fit Merton's jump diffusion to log returns r_t = ln(S_t / S_{t-1}).

    Diffusion (mu, sigma) plus Poisson(lam) jumps with log size N(mu_j, sigma_j^2); the
    drift is compensated, kbar = exp(mu_j + sigma_j^2/2) - 1, as in Lane B's generator.
    Truncating at K = ``max_jumps`` jumps per step, each return has density

        f(r) = sum_{j=0..K} e^{-lam dt} (lam dt)^j / j!
               * phi(r; (mu - sigma^2/2 - lam kbar) dt + j mu_j, sigma^2 dt + j sigma_j^2)

    and sum ln f(r_t) is maximised with L-BFGS-B, using log-sum-exp for stability, within
    mu in [-2, 2], sigma in [1e-4, 3], lam in [0, 252], mu_j in [-1, 1],
    sigma_j in [1e-4, 1]. The starts are (1) lam = 1, mu_j = 0, sigma_j = 0.02;
    (2) lam = 5, mu_j = -0.05, sigma_j = 0.05; (3) lam = 20, mu_j = 0, sigma_j = 0.02, each
    with the GBM fit's mu and sigma; the first ``n_starts`` are run and the best log L
    kept. ``converged`` is the optimiser's success flag at that start.

    Standard errors come from the inverse of the numerical Hessian of -log L at the
    optimum (central differences). A parameter within 1e-6 of a bound has a NaN
    standard error and is left out of the Hessian; if the Hessian of the others is not
    positive definite, their standard errors are NaN too (the estimate is still
    returned). k = 5.

    Refused (never raised) for fewer than 500 returns, a constant series, invalid input
    or options, or a likelihood that cannot be evaluated. Reference: Merton (1976),
    "Option pricing when underlying stock returns are discontinuous", J. Financial
    Economics 3, 125-144; Press (1967) for the likelihood.
    """
    prepared = prepare(log_returns, "log_returns", model="merton", dt=dt)
    if isinstance(prepared, FitResult):
        return prepared
    r = prepared
    n = int(r.size)
    if isinstance(n_starts, bool) or n_starts not in (1, 2, 3):
        return refused(
            "merton", n, REFUSAL_INVALID_INPUT, f"n_starts must be 1, 2 or 3, got {n_starts!r}"
        )
    if isinstance(max_jumps, bool) or not isinstance(max_jumps, int) or max_jumps < 1:
        return refused(
            "merton",
            n,
            REFUSAL_INVALID_INPUT,
            f"max_jumps must be an integer >= 1, got {max_jumps!r}",
        )
    if n < MIN_OBS_MERTON:
        return refused(
            "merton",
            n,
            REFUSAL_INSUFFICIENT_HISTORY,
            f"Merton needs at least {MIN_OBS_MERTON} observations, got {n}",
        )
    if np.ptp(r) == 0:
        return refused("merton", n, REFUSAL_CONSTANT_SERIES, "the returns have zero variance")
    return guarded("merton", n, lambda: _fit(r, dt, n_starts, max_jumps))


def log_density(
    theta: NDArray[np.float64],
    r: NDArray[np.float64],
    dt: float,
    jumps: NDArray[np.float64],
    log_factorials: NDArray[np.float64],
) -> NDArray[np.float64]:
    """ln f(r_t) for each return: the log of the Poisson-weighted Gaussian mixture over
    j = 0..K jumps in one step, combined with log-sum-exp so no term under- or overflows.

    Given j jumps, the step's log return is Gaussian with mean
    (mu - sigma^2/2 - lam kbar) dt + j mu_j and variance sigma^2 dt + j sigma_j^2, and j
    has the Poisson(lam dt) weight e^{-lam dt} (lam dt)^j / j!.
    """
    mu, sigma, lam, mu_j, sigma_j = (float(v) for v in theta)
    with np.errstate(all="ignore"):
        kbar = math.expm1(mu_j + 0.5 * sigma_j**2)
        if lam > 0:
            log_w = -lam * dt + jumps * math.log(lam * dt) - log_factorials
        else:
            log_w = np.where(jumps == 0, 0.0, -np.inf)
        mean = (mu - 0.5 * sigma**2 - lam * kbar) * dt + jumps * mu_j
        var = sigma**2 * dt + jumps * sigma_j**2
        log_phi = -0.5 * np.log(2 * math.pi * var) - (r[:, None] - mean) ** 2 / (2 * var)
        out: NDArray[np.float64] = np.asarray(logsumexp(log_w + log_phi, axis=1), dtype=np.float64)
    return out


def neg_log_likelihood(
    theta: NDArray[np.float64],
    r: NDArray[np.float64],
    dt: float,
    jumps: NDArray[np.float64],
    log_factorials: NDArray[np.float64],
) -> float:
    """-log L = -sum ln f(r_t) of (mu, sigma, lam, mu_j, sigma_j), or a large penalty where
    it is not finite (so the optimiser backs off instead of failing)."""
    with np.errstate(all="ignore"):
        total = float(np.sum(log_density(theta, r, dt, jumps, log_factorials)))
    return -total if math.isfinite(total) else _PENALTY


def _fit(r: NDArray[np.float64], dt: float, n_starts: int, max_jumps: int) -> FitResult:
    n = int(r.size)
    gbm = fit_gbm(r, dt)
    if gbm.refused:
        return refused("merton", n, REFUSAL_NUMERICAL_FAILURE, "the GBM start could not be fitted")
    mu0 = min(max(gbm.params["mu"], BOUNDS[0][0]), BOUNDS[0][1])
    sigma0 = min(max(gbm.params["sigma"], BOUNDS[1][0]), BOUNDS[1][1])
    starts = [
        (mu0, sigma0, 1.0, 0.0, 0.02),
        (mu0, sigma0, 5.0, -0.05, 0.05),
        (mu0, sigma0, 20.0, 0.0, 0.02),
    ][:n_starts]

    jumps = np.arange(max_jumps + 1, dtype=np.float64)
    log_factorials = np.asarray(gammaln(jumps + 1), dtype=np.float64)
    args = (r, dt, jumps, log_factorials)
    best_x: NDArray[np.float64] | None = None
    best_value = math.inf
    best_success = False
    for start in starts:
        result = minimize(
            neg_log_likelihood, np.array(start), args=args, method="L-BFGS-B", bounds=BOUNDS
        )
        value = float(result.fun)
        if value < best_value:
            best_x, best_value, best_success = (
                np.asarray(result.x, dtype=np.float64),
                value,
                bool(result.success),
            )
    if best_x is None or best_value >= _PENALTY:
        return refused(
            "merton", n, REFUSAL_NUMERICAL_FAILURE, "the likelihood could not be evaluated"
        )

    se = _standard_errors(best_x, lambda t: neg_log_likelihood(t, *args))
    log_likelihood = -best_value
    return FitResult(
        model="merton",
        params={name: float(v) for name, v in zip(PARAMS, best_x, strict=True)},
        std_errors={name: float(v) for name, v in zip(PARAMS, se, strict=True)},
        log_likelihood=log_likelihood,
        aic=aic(5, log_likelihood),
        n_obs=n,
        converged=best_success,
    )


def _standard_errors(theta: NDArray[np.float64], f: Objective) -> NDArray[np.float64]:
    """sqrt(diag(H^-1)) of the central-difference Hessian H of f at theta, over the
    parameters off their bounds; NaN for the others, and for all if H is not positive
    definite."""
    lo = np.array([b[0] for b in BOUNDS])
    hi = np.array([b[1] for b in BOUNDS])
    se = np.full(theta.size, np.nan)
    free = [int(i) for i in np.flatnonzero((theta - lo > ON_BOUND) & (hi - theta > ON_BOUND))]
    if not free:
        return se
    # Steps of 1e-4 relative, shrunk so that theta +- h stays inside the bounds
    h = [
        float(v)
        for v in np.minimum(
            1e-4 * np.maximum(1.0, np.abs(theta)), np.minimum(theta - lo, hi - theta)
        )
    ]

    def at(*moves: tuple[int, float]) -> float:
        point = theta.copy()
        for index, step in moves:
            point[index] += step
        return f(point)

    f0 = f(theta)
    k = len(free)
    hessian = np.empty((k, k))
    for a, i in enumerate(free):
        hessian[a, a] = (at((i, h[i])) - 2 * f0 + at((i, -h[i]))) / h[i] ** 2
        for b in range(a + 1, k):
            j = free[b]
            hessian[a, b] = hessian[b, a] = (
                at((i, h[i]), (j, h[j]))
                - at((i, h[i]), (j, -h[j]))
                - at((i, -h[i]), (j, h[j]))
                + at((i, -h[i]), (j, -h[j]))
            ) / (4 * h[i] * h[j])
    try:
        np.linalg.cholesky(hessian)
    except np.linalg.LinAlgError:
        return se
    se[free] = np.sqrt(np.diag(np.linalg.inv(hessian)))
    return se
