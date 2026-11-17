"""Exact geometric Brownian motion."""

import numpy as np

from qs_simulation.domain.generators.checks import Array, check_param, check_shocks


def simulate_gbm(s0: Array, mu: Array, sigma: Array, dt: float, shocks: Array) -> Array:
    """Prices at steps 1..steps for every path and instrument.

    ``shocks`` holds standard normal draws of shape (paths, steps, instruments), already
    correlated across instruments when they should be. The other arguments have one value
    per instrument. The step is exact for any ``dt``:
    ``log S(t+dt) = log S(t) + (mu - sigma^2 / 2) dt + sigma sqrt(dt) Z``.
    """
    n = check_shocks(shocks, dt)
    check_param("s0", s0, n, positive=True)
    check_param("mu", mu, n)
    check_param("sigma", sigma, n, positive=True)
    log_steps = (mu - 0.5 * sigma**2) * dt + sigma * np.sqrt(dt) * shocks
    out: Array = s0 * np.exp(np.cumsum(log_steps, axis=1))
    return out
