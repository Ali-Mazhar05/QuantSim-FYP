"""Exact geometric Brownian motion."""

import numpy as np

from qs_simulation.domain.generators.checks import (
    Array,
    check_param,
    check_shocks,
    check_vol_scale,
)


def simulate_gbm(
    s0: Array,
    mu: Array,
    sigma: Array,
    dt: float,
    shocks: Array,
    vol_scale: Array | None = None,
) -> Array:
    """Prices at steps 1..steps for every path and instrument.

    ``shocks`` holds standard normal draws of shape (paths, steps, instruments), already
    correlated across instruments when they should be. The other arguments have one value
    per instrument; ``vol_scale``, when given, multiplies sigma at each step (a stress scenario).
    The step is exact for any ``dt``:
    ``log S(t+dt) = log S(t) + (mu - sigma^2 / 2) dt + sigma sqrt(dt) Z``.
    """
    n = check_shocks(shocks, dt)
    check_param("s0", s0, n, positive=True)
    check_param("mu", mu, n)
    check_param("sigma", sigma, n, positive=True)
    check_vol_scale(vol_scale, shocks.shape[1])
    sig = sigma if vol_scale is None else sigma * vol_scale[:, None]  # (steps, instruments)
    log_steps = (mu - 0.5 * sig**2) * dt + sig * np.sqrt(dt) * shocks
    out: Array = s0 * np.exp(np.cumsum(log_steps, axis=1))
    return out
