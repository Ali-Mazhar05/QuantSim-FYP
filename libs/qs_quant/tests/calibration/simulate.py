"""Seeded reference simulators for the recovery tests: the exact GBM and OU steps and the
compensated Merton step, with the same formulas as Lane B's path generators."""

import math

import numpy as np
from numpy.typing import NDArray

DT = 1 / 252

GBM_TRUE = {"mu": 0.08, "sigma": 0.2}
OU_TRUE = {"kappa": 5.0, "theta": math.log(100.0), "sigma": 0.3}
MERTON_TRUE = {"mu": 0.05, "sigma": 0.15, "lam": 10.0, "mu_j": -0.03, "sigma_j": 0.04}


def rng(model: str, replication: int) -> np.random.Generator:
    """An independent, reproducible stream per model and replication."""
    return np.random.default_rng([sum(map(ord, model)), replication])


def gbm_log_returns(
    g: np.random.Generator, n: int, mu: float, sigma: float, dt: float = DT
) -> NDArray[np.float64]:
    return (mu - sigma**2 / 2) * dt + sigma * math.sqrt(dt) * g.standard_normal(n)


def ou_log_prices(
    g: np.random.Generator, n: int, kappa: float, theta: float, sigma: float, dt: float = DT
) -> NDArray[np.float64]:
    """n transitions (n + 1 log prices) of the exact OU step, starting at theta."""
    b = math.exp(-kappa * dt)
    scale = sigma * math.sqrt(-math.expm1(-2 * kappa * dt) / (2 * kappa))
    shocks = g.standard_normal(n)
    x = np.empty(n + 1)
    x[0] = theta
    for t in range(n):
        x[t + 1] = theta + (x[t] - theta) * b + scale * shocks[t]
    return x


def random_walk(g: np.random.Generator, n: int, step: float = 0.02) -> NDArray[np.float64]:
    """n transitions of a Gaussian random walk in log price (not mean-reverting)."""
    return math.log(100.0) + np.concatenate([[0.0], np.cumsum(g.normal(0.0, step, n))])


def merton_log_returns(
    g: np.random.Generator,
    n: int,
    mu: float,
    sigma: float,
    lam: float,
    mu_j: float,
    sigma_j: float,
    dt: float = DT,
) -> NDArray[np.float64]:
    counts = g.poisson(lam * dt, n)
    kbar = math.expm1(mu_j + sigma_j**2 / 2)
    diffusion = (mu - sigma**2 / 2 - lam * kbar) * dt + sigma * math.sqrt(dt) * g.standard_normal(n)
    jumps = counts * mu_j + sigma_j * np.sqrt(counts) * g.standard_normal(n)
    out: NDArray[np.float64] = diffusion + jumps
    return out
