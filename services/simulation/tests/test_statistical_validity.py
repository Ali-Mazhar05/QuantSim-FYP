"""The 3-standard-error rule must not be luck. Across many seeds a correct generator exceeds 3
standard errors about 0.3 percent of the time; this test counts the exceedances so a fixed seed
that happens to pass cannot hide a biased generator, and a flaky threshold shows up here."""

import numpy as np

from qs_simulation.domain.generators import simulate_gbm, simulate_ou
from tests.stats import z_mean, z_variance

DT = 1 / 252
SEEDS = 200
PATHS = 2_000
STEPS = 21
ONE = np.array([1.0])


def exceedances(run: object, mean: float, variance: float) -> int:
    count = 0
    for seed in range(SEEDS):
        shocks = np.random.default_rng(10_000 + seed).standard_normal((PATHS, STEPS, 1))
        log_terminal = np.log(run(shocks)[:, -1, :])  # type: ignore[operator]
        count += int(np.abs(z_mean(log_terminal, mean)[0]) > 3)
        count += int(np.abs(z_variance(log_terminal, variance)[0]) > 3)
    return count


def test_gbm_rarely_exceeds_three_standard_errors() -> None:
    horizon = STEPS * DT
    mu, sigma = 0.10, 0.30
    found = exceedances(
        lambda z: simulate_gbm(ONE * 100, ONE * mu, ONE * sigma, DT, z),
        float(np.log(100) + (mu - 0.5 * sigma**2) * horizon),
        sigma**2 * horizon,
    )
    assert found <= 4  # expected about 1 in 400 checks


def test_ou_rarely_exceeds_three_standard_errors() -> None:
    horizon = STEPS * DT
    kappa, theta, sigma = 5.0, float(np.log(120)), 0.35
    mean = theta + (np.log(100) - theta) * np.exp(-kappa * horizon)
    variance = sigma**2 / (2 * kappa) * (1 - np.exp(-2 * kappa * horizon))
    found = exceedances(
        lambda z: simulate_ou(ONE * 100, ONE * kappa, ONE * theta, ONE * sigma, DT, z),
        float(mean),
        float(variance),
    )
    assert found <= 4
