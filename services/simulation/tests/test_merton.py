"""B-FR-10, B-NFR-06: Merton jump diffusion against closed form (compensated drift)."""

import numpy as np
import pytest

from qs_simulation.domain.generators import simulate_gbm, simulate_merton
from tests.stats import z_mean, z_variance

DT = 1 / 252
STEPS = 252
PATHS = 20_000
S0 = np.array([100.0, 50.0, 250.0])
MU = np.array([0.08, -0.03, 0.15])
SIGMA = np.array([0.20, 0.35, 0.30])
LAM = np.array([3.0, 1.0, 5.0])
MU_J = np.array([-0.05, 0.02, -0.08])
SIGMA_J = np.array([0.08, 0.05, 0.10])


def draws(seed: int, paths: int = PATHS, steps: int = STEPS) -> tuple[np.ndarray, ...]:
    rng = np.random.default_rng(seed)
    shape = (paths, steps, 3)
    shocks = rng.standard_normal(shape)
    counts = rng.poisson(LAM * DT, size=shape).astype(np.int64)
    return shocks, counts, rng.standard_normal(shape)


def run(seed: int = 31, **overrides: np.ndarray) -> np.ndarray:
    shocks, counts, jump_normals = draws(seed)
    args = {"mu": MU, "sigma": SIGMA, "lam": LAM, "mu_j": MU_J, "sigma_j": SIGMA_J} | overrides
    return simulate_merton(
        S0, dt=DT, shocks=shocks, counts=counts, jump_normals=jump_normals, **args
    )


def test_the_compensated_drift_keeps_the_expected_price_on_the_drift_line() -> None:
    price = run()[:, -1, :]
    assert np.all(np.abs(z_mean(price, S0 * np.exp(MU * STEPS * DT))) < 3)


def test_terminal_log_price_matches_closed_form() -> None:
    horizon = STEPS * DT
    k = np.expm1(MU_J + 0.5 * SIGMA_J**2)
    mean = np.log(S0) + (MU - 0.5 * SIGMA**2 - LAM * k + LAM * MU_J) * horizon
    variance = (SIGMA**2 + LAM * (MU_J**2 + SIGMA_J**2)) * horizon
    terminal = np.log(run()[:, -1, :])
    assert np.all(np.abs(z_mean(terminal, mean)) < 3)
    assert np.all(np.abs(z_variance(terminal, variance)) < 3)


def test_the_compensator_is_exact_with_millions_of_one_step_paths() -> None:
    # E[S] = S0 e^(mu T) holds step by step, so one big step isolates the compensator. Without it
    # the mean would be off by lam k, about 14 percent for the first instrument; with 3 million
    # paths the standard error is 0.03 percent, so any real error shows at once.
    rng = np.random.default_rng(2024)
    shape = (3_000_000, 1, 3)
    price = simulate_merton(
        S0,
        MU,
        SIGMA,
        LAM,
        MU_J,
        SIGMA_J,
        1.0,
        rng.standard_normal(shape),
        rng.poisson(LAM, size=shape).astype(np.int64),
        rng.standard_normal(shape),
    )[:, -1, :]
    assert np.all(np.abs(z_mean(price, S0 * np.exp(MU))) < 3)
    assert np.all(np.abs(price.mean(axis=0) / (S0 * np.exp(MU)) - 1) < 5e-4)


def test_with_no_jumps_it_is_exactly_gbm() -> None:
    shocks, counts, jump_normals = draws(32, paths=200, steps=40)
    merton = simulate_merton(
        S0, MU, SIGMA, np.zeros(3), MU_J, SIGMA_J, DT, shocks, np.zeros_like(counts), jump_normals
    )
    np.testing.assert_allclose(merton, simulate_gbm(S0, MU, SIGMA, DT, shocks), rtol=1e-12)


def test_one_known_jump_multiplies_the_price_by_its_size() -> None:
    shocks = np.zeros((1, 3, 3))
    counts = np.zeros((1, 3, 3), dtype=np.int64)
    counts[0, 1, :] = 1  # one jump at step 2
    normals = np.zeros_like(shocks)  # so each jump is exactly mu_j
    jumped = simulate_merton(S0, MU, SIGMA, LAM, MU_J, SIGMA_J, DT, shocks, counts, normals)
    base = simulate_merton(S0, MU, SIGMA, LAM, MU_J, SIGMA_J, DT, shocks, 0 * counts, normals)
    np.testing.assert_allclose(jumped[0, 0], base[0, 0], rtol=1e-12)
    np.testing.assert_allclose(jumped[0, 1] / base[0, 1], np.exp(MU_J), rtol=1e-12)
    np.testing.assert_allclose(jumped[0, 2] / base[0, 2], np.exp(MU_J), rtol=1e-12)


@pytest.mark.parametrize(
    ("field", "value", "words"),
    [
        ("lam", np.array([3.0, -1.0, 5.0]), "lam must not be negative"),
        ("sigma_j", np.array([0.1, -0.1, 0.1]), "sigma_j must not be negative"),
        ("sigma", np.array([0.2, 0.0, 0.3]), "sigma must be positive"),
        ("mu_j", np.array([0.0, np.nan, 0.0]), "mu_j must be finite"),
    ],
)
def test_bad_parameters_name_the_field(field: str, value: np.ndarray, words: str) -> None:
    shocks, counts, normals = draws(33, paths=5, steps=3)
    args = {"mu": MU, "sigma": SIGMA, "lam": LAM, "mu_j": MU_J, "sigma_j": SIGMA_J, field: value}
    with pytest.raises(ValueError, match=words):
        simulate_merton(S0, dt=DT, shocks=shocks, counts=counts, jump_normals=normals, **args)


def test_bad_jump_draws_are_refused() -> None:
    shocks, counts, normals = draws(34, paths=5, steps=3)
    not_finite = normals.copy()
    not_finite[0, 0, 0] = np.nan
    with pytest.raises(ValueError, match="jump_normals must be finite"):
        simulate_merton(S0, MU, SIGMA, LAM, MU_J, SIGMA_J, DT, shocks, counts, not_finite)
    with pytest.raises(ValueError, match="same shape"):
        simulate_merton(S0, MU, SIGMA, LAM, MU_J, SIGMA_J, DT, shocks, counts[:, :2], normals)
    with pytest.raises(ValueError, match="counts must not be negative"):
        simulate_merton(S0, MU, SIGMA, LAM, MU_J, SIGMA_J, DT, shocks, counts - 1, normals)
