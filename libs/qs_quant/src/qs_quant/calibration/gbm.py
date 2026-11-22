"""Geometric Brownian motion by closed-form maximum likelihood (K5, C-FR-01; guide §7.2)."""

import math

import numpy as np
from numpy.typing import NDArray

from qs_quant._validation import Series
from qs_quant.calibration._common import guarded, prepare
from qs_quant.calibration.result import (
    REFUSAL_CONSTANT_SERIES,
    REFUSAL_INSUFFICIENT_HISTORY,
    FitResult,
    aic,
    refused,
)

__all__ = ["MIN_OBS_GBM", "fit_gbm"]

MIN_OBS_GBM = 60
"""The fewest log returns fit_gbm accepts."""


def fit_gbm(log_returns: Series, dt: float = 1 / 252) -> FitResult:
    """Fit GBM dS = mu S dt + sigma S dW to log returns r_t = ln(S_t / S_{t-1}).

    Log returns are i.i.d. N((mu - sigma^2/2) dt, sigma^2 dt). With m = mean(r) and
    s^2 = (1/n) sum (r_t - m)^2 (the MLE, ddof = 0):

        sigma = s / sqrt(dt)            mu = m / dt + sigma^2 / 2
        se(sigma) = sigma / sqrt(2 n)   se(mu) = sigma / sqrt(n dt)
        log L = -(n/2) ln(2 pi s^2) - n/2,  k = 2

    se(mu) is the delta-method error of m / dt; the sigma^2/2 term adds a variance of
    sigma^4 / (2n), smaller by a factor sigma^2 dt / 2 (about 1e-4 for daily data), and is
    neglected. Reference: Campbell, Lo and MacKinlay (1997), The Econometrics of
    Financial Markets, ch. 9.

    Refused (never raised) for invalid input, fewer than 60 returns, or zero variance.
    """
    prepared = prepare(log_returns, "log_returns", model="gbm", dt=dt)
    if isinstance(prepared, FitResult):
        return prepared
    r = prepared
    n = int(r.size)
    if n < MIN_OBS_GBM:
        return refused(
            "gbm",
            n,
            REFUSAL_INSUFFICIENT_HISTORY,
            f"GBM needs at least {MIN_OBS_GBM} observations, got {n}",
        )
    if np.ptp(r) == 0:
        return refused("gbm", n, REFUSAL_CONSTANT_SERIES, "the returns have zero variance")
    return guarded("gbm", n, lambda: _fit(r, dt))


def _fit(r: NDArray[np.float64], dt: float) -> FitResult:
    n = int(r.size)
    m = float(np.mean(r))
    s2 = float(np.mean((r - m) ** 2))
    sigma = math.sqrt(s2 / dt)
    mu = m / dt + sigma**2 / 2
    log_likelihood = -(n / 2) * math.log(2 * math.pi * s2) - n / 2
    return FitResult(
        model="gbm",
        params={"mu": mu, "sigma": sigma},
        std_errors={"mu": sigma / math.sqrt(n * dt), "sigma": sigma / math.sqrt(2 * n)},
        log_likelihood=log_likelihood,
        aic=aic(2, log_likelihood),
        n_obs=n,
        converged=True,
    )
