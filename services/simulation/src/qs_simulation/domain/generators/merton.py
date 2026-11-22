"""Merton jump diffusion with compensated drift (ADR 02)."""

import numpy as np
from numpy.typing import NDArray

from qs_simulation.domain.generators.checks import Array, check_param, check_shocks

Counts = NDArray[np.int64]


def simulate_merton(
    s0: Array,
    mu: Array,
    sigma: Array,
    lam: Array,
    mu_j: Array,
    sigma_j: Array,
    dt: float,
    shocks: Array,
    counts: Counts,
    jump_normals: Array,
) -> Array:
    """Prices at steps 1..steps for every path and instrument.

    Per step the log price moves by the GBM step with drift ``mu - sigma^2/2 - lam k`` plus the
    sum of ``N`` jumps, ``N ~ Poisson(lam dt)`` (given as ``counts``), each ``Y ~ N(mu_j,
    sigma_j^2)``. Given ``N`` that sum is exactly ``N mu_j + sigma_j sqrt(N) Z`` with ``Z`` a
    standard normal (``jump_normals``). ``k = exp(mu_j + sigma_j^2/2) - 1`` is the mean relative
    jump, so subtracting ``lam k`` keeps ``E[S(t)] = S(0) e^(mu t)``. Jumps are independent
    across instruments; only the diffusion shocks are correlated.
    """
    n = check_shocks(shocks, dt)
    check_param("s0", s0, n, positive=True)
    check_param("mu", mu, n)
    check_param("sigma", sigma, n, positive=True)
    check_param("lam", lam, n, non_negative=True)
    check_param("mu_j", mu_j, n)
    check_param("sigma_j", sigma_j, n, non_negative=True)
    if counts.shape != shocks.shape or jump_normals.shape != shocks.shape:
        raise ValueError("counts and jump_normals must have the same shape as shocks")
    if np.any(counts < 0):
        raise ValueError("counts must not be negative")
    if not np.all(np.isfinite(jump_normals)):
        raise ValueError("jump_normals must be finite")
    k = np.expm1(mu_j + 0.5 * sigma_j**2)
    jumps = counts * mu_j + sigma_j * np.sqrt(counts) * jump_normals
    log_steps = (mu - 0.5 * sigma**2 - lam * k) * dt + sigma * np.sqrt(dt) * shocks + jumps
    out: Array = s0 * np.exp(np.cumsum(log_steps, axis=1))
    return out
