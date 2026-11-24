"""Exact Ornstein-Uhlenbeck on log price (ADR 02)."""

import numpy as np

from qs_simulation.domain.generators.checks import (
    Array,
    check_param,
    check_shocks,
    check_vol_scale,
)


def simulate_ou(
    s0: Array,
    kappa: Array,
    theta: Array,
    sigma: Array,
    dt: float,
    shocks: Array,
    vol_scale: Array | None = None,
) -> Array:
    """Prices at steps 1..steps for every path and instrument.

    The calibration fits log prices, so the process runs on ``X = log S`` and the result is
    ``exp(X)``. ``theta`` is the long-run level of log price. ``vol_scale``, when given, multiplies
    sigma at each step (a stress scenario). The step is exact for any ``dt``:
    ``X(t+dt) = theta + (X(t) - theta) e^(-kappa dt)
    + sigma sqrt((1 - e^(-2 kappa dt)) / (2 kappa)) Z``.
    """
    n = check_shocks(shocks, dt)
    check_param("s0", s0, n, positive=True)
    check_param("kappa", kappa, n, positive=True)
    check_param("theta", theta, n)
    check_param("sigma", sigma, n, positive=True)
    check_vol_scale(vol_scale, shocks.shape[1])
    decay = np.exp(-kappa * dt)
    scale = sigma * np.sqrt(-np.expm1(-2.0 * kappa * dt) / (2.0 * kappa))
    x = np.broadcast_to(np.log(s0), (shocks.shape[0], n))
    log_path = np.empty_like(shocks)
    for t in range(shocks.shape[1]):  # the recursion is sequential in time, vector over paths
        step_scale = scale if vol_scale is None else scale * vol_scale[t]
        x = theta + (x - theta) * decay + step_scale * shocks[:, t, :]
        log_path[:, t, :] = x
    out: Array = np.exp(log_path)
    return out
