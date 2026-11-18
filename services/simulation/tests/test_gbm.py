"""B-FR-10, B-NFR-06: exact GBM against closed form, at the 20,000 paths the plan names."""

import numpy as np
import pytest

from qs_simulation.domain.generators import simulate_gbm
from tests.stats import z_mean, z_variance

DT = 1 / 252
STEPS = 252
PATHS = 20_000
S0 = np.array([100.0, 50.0, 250.0])
MU = np.array([0.08, -0.03, 0.15])
SIGMA = np.array([0.20, 0.35, 0.60])


def draw(seed: int, paths: int = PATHS, steps: int = STEPS, n: int = 3) -> np.ndarray:
    return np.random.default_rng(seed).standard_normal((paths, steps, n))


def test_terminal_log_price_matches_closed_form() -> None:
    horizon = STEPS * DT
    terminal = np.log(simulate_gbm(S0, MU, SIGMA, DT, draw(1))[:, -1, :])
    mean = np.log(S0) + (MU - 0.5 * SIGMA**2) * horizon
    variance = SIGMA**2 * horizon
    assert np.all(np.abs(z_mean(terminal, mean)) < 3)
    assert np.all(np.abs(z_variance(terminal, variance)) < 3)


def test_expected_terminal_price_is_the_drifted_start() -> None:
    price = simulate_gbm(S0, MU, SIGMA, DT, draw(2))[:, -1, :]
    assert np.all(np.abs(z_mean(price, S0 * np.exp(MU * STEPS * DT))) < 3)


def test_zero_shocks_follow_the_deterministic_drift() -> None:
    shocks = np.zeros((2, 10, 3))
    paths = simulate_gbm(S0, MU, SIGMA, DT, shocks)
    t = np.arange(1, 11)[:, None]
    expected = S0 * np.exp((MU - 0.5 * SIGMA**2) * DT * t)
    np.testing.assert_allclose(paths[0], expected, rtol=1e-12)
    np.testing.assert_array_equal(paths[0], paths[1])


def test_same_shocks_give_identical_paths_and_prices_stay_positive() -> None:
    shocks = draw(3, paths=500, steps=30)
    first = simulate_gbm(S0, MU, SIGMA, DT, shocks)
    np.testing.assert_array_equal(first, simulate_gbm(S0, MU, SIGMA, DT, shocks))
    assert first.shape == (500, 30, 3) and np.all(first > 0)


@pytest.mark.parametrize(
    ("field", "value", "words"),
    [
        ("s0", np.array([100.0, -1.0, 250.0]), "s0 must be positive"),
        ("sigma", np.array([0.2, 0.0, 0.6]), "sigma must be positive"),
        ("mu", np.array([0.1, np.nan, 0.1]), "mu must be finite"),
        ("mu", np.array([0.1, 0.1]), "one value per instrument"),
    ],
)
def test_bad_parameters_name_the_field(field: str, value: np.ndarray, words: str) -> None:
    args = {"s0": S0, "mu": MU, "sigma": SIGMA, field: value}
    with pytest.raises(ValueError, match=words):
        simulate_gbm(args["s0"], args["mu"], args["sigma"], DT, draw(4, paths=5, steps=3))


def test_bad_shocks_and_step_are_refused() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        simulate_gbm(S0, MU, SIGMA, DT, np.zeros((0, 3, 3)))
    with pytest.raises(ValueError, match="shape"):
        simulate_gbm(S0, MU, SIGMA, DT, np.zeros((5, 3)))
    with pytest.raises(ValueError, match="dt must be positive"):
        simulate_gbm(S0, MU, SIGMA, 0.0, draw(5, paths=5, steps=3))
    with pytest.raises(ValueError, match="finite"):
        bad = draw(6, paths=5, steps=3)
        bad[0, 0, 0] = np.inf
        simulate_gbm(S0, MU, SIGMA, DT, bad)
