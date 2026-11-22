"""Ornstein-Uhlenbeck on log price by AR(1) with a unit-root refusal (K5, C-FR-02; guide §7.3)."""

import math

import numpy as np
from numpy.typing import NDArray
from statsmodels.tsa.stattools import adfuller

from qs_quant._validation import Series
from qs_quant.calibration._common import guarded, prepare
from qs_quant.calibration.result import (
    REFUSAL_CONSTANT_SERIES,
    REFUSAL_INSUFFICIENT_HISTORY,
    REFUSAL_NOT_MEAN_REVERTING,
    FitResult,
    aic,
    refused,
)

__all__ = ["ADF_LEVEL", "MIN_OBS_OU", "fit_ou"]

MIN_OBS_OU = 60
"""The fewest transitions (log prices minus one) fit_ou accepts."""
ADF_LEVEL = 0.05
"""A series is refused unless the ADF test rejects a unit root at this level."""


def fit_ou(log_prices: Series, dt: float = 1 / 252) -> FitResult:
    """Fit OU dX = kappa (theta - X) dt + sigma dW to log prices X_t = ln S_t.

    The exact discretisation is the AR(1) model X_{t+1} = a + b X_t + e_t,
    e_t ~ N(0, s^2), so the conditional MLE is ordinary least squares, with
    s^2 = RSS / n over the n transitions and

        b = exp(-kappa dt),  a = theta (1 - b),  s^2 = sigma^2 (1 - b^2) / (2 kappa)
        kappa = -ln(b) / dt, theta = a / (1 - b), sigma = s sqrt(2 kappa / (1 - b^2))

    Standard errors by the delta method from the OLS covariance s^2 (X'X)^-1 of (a, b)
    and se(s) = s / sqrt(2n). log L is the Gaussian AR(1) residual likelihood, k = 3.

    Refused (never raised) when the augmented Dickey-Fuller test (constant, lag order by
    AIC) does not reject a unit root at 5%: a random walk often gives b just below 1, so
    b alone cannot tell it apart. Also refused when b is outside (0, 1), for fewer than
    60 transitions, for a constant series and for invalid input.

    References: Vasicek (1977); Dickey and Fuller (1979); MacKinnon (1994) for the ADF
    p-value (statsmodels.tsa.stattools.adfuller).
    """
    prepared = prepare(log_prices, "log_prices", model="ou", dt=dt)
    if isinstance(prepared, FitResult):
        return prepared
    x = prepared
    n = max(int(x.size) - 1, 0)
    if n < MIN_OBS_OU:
        return refused(
            "ou",
            n,
            REFUSAL_INSUFFICIENT_HISTORY,
            f"OU needs at least {MIN_OBS_OU} observations (transitions), got {n}",
        )
    if np.ptp(x) == 0:
        return refused("ou", n, REFUSAL_CONSTANT_SERIES, "the log prices do not move")
    return guarded("ou", n, lambda: _fit(x, dt))


def _fit(x: NDArray[np.float64], dt: float) -> FitResult:
    n = int(x.size) - 1
    p_value = float(adfuller(x, regression="c", autolag="AIC", result_object=True).pvalue)
    if not p_value < ADF_LEVEL:
        return refused(
            "ou",
            n,
            REFUSAL_NOT_MEAN_REVERTING,
            f"series is not mean-reverting (ADF p = {p_value:.2f})",
        )

    # OLS of y = x[1:] on [1, x[:-1]] in centred form, which is the same estimate as a
    # generic least-squares solve but loses less precision when b is close to 1
    lag, y = x[:-1], x[1:]
    lag_mean, y_mean = float(np.mean(lag)), float(np.mean(y))
    lag_c = lag - lag_mean
    sxx = float(lag_c @ lag_c)
    b = float(lag_c @ (y - y_mean)) / sxx
    a = y_mean - b * lag_mean
    if not 0 < b < 1:
        return refused(
            "ou", n, REFUSAL_NOT_MEAN_REVERTING, f"AR(1) coefficient b = {b:.6f} outside (0, 1)"
        )
    resid = y - (a + b * lag)
    s2 = float(resid @ resid) / n
    if s2 == 0:
        return refused("ou", n, REFUSAL_CONSTANT_SERIES, "the AR(1) residuals have zero variance")
    s = math.sqrt(s2)

    kappa = -math.log(b) / dt
    theta = a / (1 - b)
    sigma = s * math.sqrt(2 * kappa / (1 - b * b))

    # Covariance of (a, b, s): the OLS block s^2 (X'X)^-1 and var(s) = s^2 / (2n)
    cov = np.zeros((3, 3))
    cov[0, 0] = s2 * (1 / n + lag_mean**2 / sxx)
    cov[0, 1] = cov[1, 0] = -s2 * lag_mean / sxx
    cov[1, 1] = s2 / sxx
    cov[2, 2] = s2 / (2 * n)
    jac = ou_jacobian(a, b, s, dt)
    se = np.sqrt(np.diag(jac @ cov @ jac.T))

    log_likelihood = -(n / 2) * math.log(2 * math.pi * s2) - n / 2
    return FitResult(
        model="ou",
        params={"kappa": kappa, "theta": theta, "sigma": sigma},
        std_errors={"kappa": float(se[0]), "theta": float(se[1]), "sigma": float(se[2])},
        log_likelihood=log_likelihood,
        aic=aic(3, log_likelihood),
        n_obs=n,
        converged=True,
    )


def ou_jacobian(a: float, b: float, s: float, dt: float) -> NDArray[np.float64]:
    """d(kappa, theta, sigma) / d(a, b, s), the delta-method Jacobian of the OU transform.

    With g(b) = 2 kappa / (1 - b^2), sigma = s sqrt(g):
    dkappa/db = -1 / (b dt); dtheta/da = 1 / (1 - b); dtheta/db = a / (1 - b)^2;
    dg/db = (2 dkappa/db (1 - b^2) + 4 kappa b) / (1 - b^2)^2;
    dsigma/db = s dg/db / (2 sqrt(g)); dsigma/ds = sqrt(g).
    """
    kappa = -math.log(b) / dt
    one_minus_b2 = 1 - b * b
    dkappa_db = -1 / (b * dt)
    g = 2 * kappa / one_minus_b2
    dg_db = (2 * dkappa_db * one_minus_b2 + 4 * kappa * b) / one_minus_b2**2
    sqrt_g = math.sqrt(g)
    return np.array(
        [
            [0.0, dkappa_db, 0.0],
            [1 / (1 - b), a / (1 - b) ** 2, 0.0],
            [0.0, s * dg_db / (2 * sqrt_g), sqrt_g],
        ]
    )
