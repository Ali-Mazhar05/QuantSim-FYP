"""B-FR-10, B-NFR-06: exact OU on log price against closed form."""

import numpy as np
import pytest

from qs_simulation.domain.generators import simulate_ou
from tests.stats import z_mean, z_variance

DT = 1 / 252
STEPS = 252
PATHS = 20_000
S0 = np.array([100.0, 40.0, 300.0])
KAPPA = np.array([3.0, 8.0, 1.5])
THETA = np.array([np.log(110.0), np.log(35.0), np.log(300.0)])
SIGMA = np.array([0.25, 0.40, 0.30])


def draw(seed: int, paths: int = PATHS, steps: int = STEPS, n: int = 3) -> np.ndarray:
    return np.random.default_rng(seed).standard_normal((paths, steps, n))


def closed_form(horizon: float) -> tuple[np.ndarray, np.ndarray]:
    mean = THETA + (np.log(S0) - THETA) * np.exp(-KAPPA * horizon)
    variance = SIGMA**2 / (2 * KAPPA) * (1 - np.exp(-2 * KAPPA * horizon))
    return mean, variance


def test_terminal_log_price_matches_closed_form() -> None:
    terminal = np.log(simulate_ou(S0, KAPPA, THETA, SIGMA, DT, draw(11))[:, -1, :])
    mean, variance = closed_form(STEPS * DT)
    assert np.all(np.abs(z_mean(terminal, mean)) < 3)
    assert np.all(np.abs(z_variance(terminal, variance)) < 3)


def test_terminal_price_mean_is_lognormal() -> None:
    price = simulate_ou(S0, KAPPA, THETA, SIGMA, DT, draw(12))[:, -1, :]
    mean, variance = closed_form(STEPS * DT)
    assert np.all(np.abs(z_mean(price, np.exp(mean + variance / 2))) < 3)


def test_zero_shocks_revert_toward_theta_exactly() -> None:
    paths = simulate_ou(S0, KAPPA, THETA, SIGMA, DT, np.zeros((1, 40, 3)))
    t = np.arange(1, 41)[:, None]
    expected = np.exp(THETA + (np.log(S0) - THETA) * np.exp(-KAPPA * DT * t))
    np.testing.assert_allclose(paths[0], expected, rtol=1e-12)


def test_it_is_a_mean_reverting_process() -> None:
    # far from theta, the average path moves toward it; a random walk would not
    start = np.array([100.0, 40.0, 300.0]) * np.array([2.0, 0.5, 1.0])
    avg = simulate_ou(start, KAPPA, THETA, SIGMA, DT, draw(13, paths=2000)).mean(axis=0)
    assert abs(np.log(avg[-1, 0]) - THETA[0]) < abs(np.log(start[0]) - THETA[0])
    assert abs(np.log(avg[-1, 1]) - THETA[1]) < abs(np.log(start[1]) - THETA[1])


@pytest.mark.parametrize(
    ("field", "value", "words"),
    [
        ("kappa", np.array([3.0, 0.0, 1.5]), "kappa must be positive"),
        ("sigma", np.array([0.2, -0.1, 0.3]), "sigma must be positive"),
        ("theta", np.array([1.0, np.inf, 1.0]), "theta must be finite"),
        ("s0", np.array([100.0, 0.0, 300.0]), "s0 must be positive"),
    ],
)
def test_bad_parameters_name_the_field(field: str, value: np.ndarray, words: str) -> None:
    args = {"s0": S0, "kappa": KAPPA, "theta": THETA, "sigma": SIGMA, field: value}
    with pytest.raises(ValueError, match=words):
        simulate_ou(
            args["s0"], args["kappa"], args["theta"], args["sigma"], DT, draw(14, paths=5, steps=3)
        )


def test_same_shocks_give_identical_paths_and_prices_stay_positive() -> None:
    shocks = draw(15, paths=300, steps=30)
    first = simulate_ou(S0, KAPPA, THETA, SIGMA, DT, shocks)
    np.testing.assert_array_equal(first, simulate_ou(S0, KAPPA, THETA, SIGMA, DT, shocks))
    assert first.shape == (300, 30, 3) and np.all(first > 0)
