"""B-NFR-06 through the whole pipeline: correlation, sharding and jumps together.

A single fixed seed is the wrong tool for a 3-standard-error rule: seed 77 on this configuration
gives -3.4 and -3.1 on two instruments, yet a 200-seed sweep of the same generator showed
z-scores with mean 0.0 to 0.1, standard deviation 1.0 and the expected 1 exceedance in 200. So
the test counts exceedances across seeds instead, which a biased generator fails and an unlucky
seed cannot."""

import numpy as np

from qs_simulation.domain.sharding import PathRequest, generate
from tests.stats import z_mean, z_variance

S0 = np.array([100.0, 50.0, 250.0, 20.0])
RHO = np.array(
    [
        [1.0, 0.7, 0.4, -0.2],
        [0.7, 1.0, 0.5, 0.0],
        [0.4, 0.5, 1.0, 0.3],
        [-0.2, 0.0, 0.3, 1.0],
    ]
)
P = {
    "mu": np.array([0.08, -0.03, 0.15, 0.05]),
    "sigma": np.array([0.20, 0.35, 0.60, 0.30]),
    "lam": np.array([3.0, 1.0, 5.0, 2.0]),
    "mu_j": np.array([-0.05, 0.02, -0.08, 0.0]),
    "sigma_j": np.array([0.08, 0.05, 0.10, 0.06]),
}
SEEDS = 40
PATHS = 2_000


def test_merton_log_price_moments_rarely_exceed_three_standard_errors() -> None:
    k = np.expm1(P["mu_j"] + 0.5 * P["sigma_j"] ** 2)
    mean = np.log(S0) + (P["mu"] - 0.5 * P["sigma"] ** 2 - P["lam"] * k + P["lam"] * P["mu_j"])
    variance = P["sigma"] ** 2 + P["lam"] * (P["mu_j"] ** 2 + P["sigma_j"] ** 2)
    z_means: list[np.ndarray] = []
    z_variances: list[np.ndarray] = []
    for seed in range(SEEDS):
        request = PathRequest("merton", S0, P, RHO, PATHS, 252, seed=2_000 + seed)
        terminal = np.log(generate(request)[0][:, -1, :])
        z_means.append(z_mean(terminal, mean))
        z_variances.append(z_variance(terminal, variance))
    zm, zv = np.array(z_means), np.array(z_variances)
    exceedances = int((np.abs(zm) > 3).sum() + (np.abs(zv) > 3).sum())
    assert exceedances <= 3  # 320 checks, about 0.9 expected
    assert np.all(np.abs(zm.mean(axis=0)) < 0.6)  # no systematic bias (standard error 0.16)
    assert np.all(np.abs(zv.mean(axis=0)) < 0.6)
