"""The pure parts of a run (B16): the storage rule, the median path, the statistics, the quantiles,
the risk formula and the resource limits. No database, no services."""

import os
import subprocess
import sys
from decimal import Decimal

import numpy as np
import pytest

from qs_simulation.adapters.risk import MIN_RETURNS, ReferenceRisk, default_risk, reference_var_cvar
from qs_simulation.domain.runs import (
    FULL_STORAGE_MAX_VALUES,
    MAX_INSTRUMENTS,
    UNSTORABLE_PATHS,
    RunRefused,
    check_paths,
    median_path_index,
    run_values,
    step_quantiles,
    storage_mode,
    terminal_statistics,
    to_price,
    to_statistic,
)
from qs_simulation.domain.sharding import PathRequest, generate, shard_sizes
from qs_simulation.runs import shard_workers

RNG = np.random.default_rng(11)


def paths_of(terminal: list[list[float]], steps: int = 3) -> np.ndarray:
    """Paths whose last step is the given terminal prices (rows: paths, columns: instruments)."""
    last = np.array(terminal, dtype=np.float64)
    out = np.repeat(last[:, None, :], steps, axis=1)
    return out


# ---- the storage rule (DL-013) ----


@pytest.mark.parametrize(
    ("paths", "steps", "instruments", "mode"),
    [
        (1000, 252, 5, "full"),  # the demo: 252,000 per instrument exactly
        (1000, 252, 10, "full"),
        (1000, 252, 11, "quantiles"),  # one instrument too many
        (1001, 252, 5, "quantiles"),  # one path too many
        (10_000, 252, 5, "quantiles"),
        (1, 1, 1, "full"),
        (20, 2_520, 1, "full"),  # 50,400
        (100_000, 2_520, 1, "quantiles"),
    ],
)
def test_the_storage_rule_is_252000_values_per_instrument_and_ten_instruments(
    paths: int, steps: int, instruments: int, mode: str
) -> None:
    assert storage_mode(paths, steps, instruments) == mode
    assert FULL_STORAGE_MAX_VALUES == 252_000


def test_a_run_holds_paths_times_steps_times_instruments_prices() -> None:
    assert run_values(1000, 252, 5) == 1_260_000


# ---- decimals at the boundary ----


def test_a_price_is_written_to_ten_places() -> None:
    assert to_price(123.456789012345) == Decimal("123.4567890123")
    assert to_price(0.5) == Decimal("0.5000000000")
    assert to_price(1e-10) == Decimal("1E-10")  # the smallest price that is kept


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -1.0, 0.0, 1e-12, 1e13, 5e20])
def test_a_price_that_cannot_be_stored_refuses_the_run(bad: float) -> None:
    with pytest.raises(RunRefused) as refused:
        to_price(bad)
    assert refused.value.code == UNSTORABLE_PATHS


def test_a_statistic_is_written_to_twelve_places_and_must_be_finite() -> None:
    assert to_statistic(0.05) == Decimal("0.050000000000")
    assert to_statistic(-0.2) == Decimal("-0.200000000000")
    with pytest.raises(RunRefused):
        to_statistic(float("nan"))


def test_paths_are_checked_once_for_the_whole_array() -> None:
    check_paths(np.full((4, 3, 2), 100.0))
    for spoiled in (np.nan, np.inf, 0.0, 1e14):
        paths = np.full((4, 3, 2), 100.0)
        paths[2, 1, 1] = spoiled
        with pytest.raises(RunRefused) as refused:
            check_paths(paths)
        assert refused.value.code == UNSTORABLE_PATHS


# ---- the median path (DL-001) ----


def test_the_median_path_is_the_lower_median_of_the_basket_terminal_value() -> None:
    # one instrument, terminals 100x the ratio; sorted ratios 0.5, 0.8, 1.0, 1.3 -> lower median 0.8
    paths = paths_of([[100.0], [50.0], [130.0], [80.0]])
    assert median_path_index(paths, np.array([100.0])) == 3
    # an odd number of paths: the middle one
    paths = paths_of([[90.0], [120.0], [100.0]])
    assert median_path_index(paths, np.array([100.0])) == 2  # 100 is the middle of 90, 100, 120


def test_ties_go_to_the_lowest_index() -> None:
    paths = paths_of([[110.0], [100.0], [100.0], [100.0], [90.0]])
    assert median_path_index(paths, np.array([100.0])) == 1
    even = paths_of([[100.0], [100.0], [100.0], [100.0]])
    assert median_path_index(even, np.array([100.0])) == 0


def test_the_basket_normalises_each_price_by_its_start_and_weights_instruments_equally() -> None:
    # instrument 0 is priced near 1,000 and instrument 1 near 2: only the ratios to the start count
    s0 = np.array([1000.0, 2.0])
    paths = paths_of([[1250.0, 1.5], [900.0, 3.0], [1000.0, 2.0]])
    # ratios: path 0 -> (1.25 + 0.75) / 2 = 1.0; path 1 -> (0.9 + 1.5) / 2 = 1.2; path 2 -> 1.0
    assert median_path_index(paths, s0) == 0  # sorted 1.0, 1.0, 1.2: lower median 1.0, lowest index
    assert median_path_index(paths_of([[1250.0, 1.5], [900.0, 3.0]]), s0) == 0


def test_the_median_path_does_not_depend_on_the_order_of_instruments() -> None:
    terminal = RNG.uniform(80, 120, size=(101, 3))
    s0 = np.array([100.0, 90.0, 110.0])
    paths = paths_of(terminal.tolist())
    swapped = paths[:, :, ::-1]
    assert median_path_index(paths, s0) == median_path_index(swapped, s0[::-1])


# ---- the statistics ----


def test_terminal_statistics_are_the_mean_median_and_percentiles_of_the_last_step() -> None:
    terminal = RNG.uniform(50, 150, size=(500, 2))
    paths = paths_of(terminal.tolist(), steps=4)
    s0 = np.array([100.0, 100.0])
    stats = terminal_statistics(paths, s0, ReferenceRisk())
    for i, summary in enumerate(stats):
        column = terminal[:, i]
        assert float(summary.mean_price) == pytest.approx(column.mean(), abs=1e-9)
        assert float(summary.median_price) == pytest.approx(np.median(column), abs=1e-9)
        assert float(summary.p5_price) == pytest.approx(np.percentile(column, 5), abs=1e-9)
        assert float(summary.p95_price) == pytest.approx(np.percentile(column, 95), abs=1e-9)
        var, cvar = reference_var_cvar(column / 100.0 - 1.0)
        assert float(summary.var95) == pytest.approx(var, abs=1e-11)
        assert float(summary.cvar95) == pytest.approx(cvar, abs=1e-11)
        assert summary.var95 <= summary.cvar95
        assert summary.p5_price <= summary.median_price <= summary.p95_price


def test_a_losing_run_has_positive_losses_and_a_gaining_run_has_negative_ones() -> None:
    losing = terminal_statistics(
        paths_of([[80.0 + i * 0.1] for i in range(100)]), np.array([100.0]), ReferenceRisk()
    )[0]
    assert losing.var95 > 0 and losing.cvar95 >= losing.var95
    gaining = terminal_statistics(
        paths_of([[120.0 + i * 0.1] for i in range(100)]), np.array([100.0]), ReferenceRisk()
    )[0]
    assert gaining.var95 < 0  # even the bad tail gained


def test_step_quantiles_are_ordered_and_match_numpy_at_every_step() -> None:
    paths = RNG.uniform(10, 200, size=(300, 12, 3))
    quantiles = step_quantiles(paths)
    assert quantiles.shape == (12, 3, 7)
    assert np.all(np.diff(quantiles, axis=-1) >= 0)
    expected = np.quantile(paths[:, 4, 2], [0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99])
    assert quantiles[4, 2] == pytest.approx(expected)


# ---- VaR and CVaR, Lane C's formula (7.6) ----


def test_var_and_cvar_follow_the_definition_on_a_worked_sample() -> None:
    returns = np.arange(-50, 50, dtype=np.float64) / 100.0  # -0.50 ... 0.49, 100 values
    var, cvar = reference_var_cvar(returns, 0.95)
    q = np.quantile(returns, 0.05)  # linear interpolation: -0.4505
    assert q == pytest.approx(-0.4505)
    assert var == pytest.approx(0.4505)
    assert cvar == pytest.approx(-returns[returns <= q].mean())  # the five worst: -0.50 ... -0.46
    assert cvar == pytest.approx(0.48)
    assert var <= cvar


@pytest.mark.parametrize("seed", range(40))
def test_cvar_is_never_below_var_and_both_scale_with_the_returns(seed: int) -> None:
    returns = np.random.default_rng(seed).normal(0.01, 0.05, size=400)
    var, cvar = reference_var_cvar(returns)
    assert cvar >= var
    scaled_var, scaled_cvar = reference_var_cvar(returns * 3.0)
    assert scaled_var == pytest.approx(var * 3.0) and scaled_cvar == pytest.approx(cvar * 3.0)


def test_var_and_cvar_need_enough_returns_and_a_sensible_alpha() -> None:
    with pytest.raises(ValueError, match="20"):
        reference_var_cvar(np.zeros(MIN_RETURNS - 1))
    with pytest.raises(ValueError, match="alpha"):
        reference_var_cvar(np.zeros(50), alpha=1.0)
    with pytest.raises(ValueError):
        reference_var_cvar(np.zeros((5, 5)))
    reference_var_cvar(np.zeros(MIN_RETURNS))  # the least that is accepted


def test_the_default_risk_is_the_specification_until_k6_is_installed() -> None:
    risk = default_risk()
    assert isinstance(risk.version, str) and risk.version
    var, cvar = risk.var_cvar(np.linspace(-0.3, 0.3, 100))
    assert (var, cvar) == pytest.approx(reference_var_cvar(np.linspace(-0.3, 0.3, 100)))


# ---- resource limits (B-NFR-14) ----


def test_the_shard_pool_leaves_one_core_free_and_never_has_fewer_than_one() -> None:
    assert shard_workers(0, cpus=8) == 7
    assert shard_workers(0, cpus=2) == 1
    assert shard_workers(0, cpus=1) == 1
    assert shard_workers(3, cpus=8) == 3  # an explicit setting wins
    assert shard_workers(0, cpus=None) >= 1


def test_the_package_keeps_blas_to_one_thread_before_numpy_is_imported() -> None:
    env = {k: v for k, v in os.environ.items() if k != "OMP_NUM_THREADS"}
    code = "import qs_simulation, os; print(os.environ['OMP_NUM_THREADS'])"
    out = subprocess.run(  # noqa: S603 - our own interpreter and a fixed snippet
        [sys.executable, "-c", code], capture_output=True, text=True, env=env
    )
    assert out.stdout.strip() == "1", out.stderr
    explicit = subprocess.run(  # noqa: S603
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env={**env, "OMP_NUM_THREADS": "4"},
    )
    assert explicit.stdout.strip() == "4"  # a deliberate setting is respected


def test_the_instrument_limit_is_the_demo_universe() -> None:
    assert MAX_INSTRUMENTS == 40


# ---- progress while generating ----


def request(n_paths: int = 600) -> PathRequest:
    return PathRequest(
        model="gbm",
        s0=np.array([100.0, 50.0]),
        params={"mu": np.array([0.1, 0.05]), "sigma": np.array([0.2, 0.3])},
        correlation=np.array([[1.0, 0.4], [0.4, 1.0]]),
        n_paths=n_paths,
        n_steps=10,
        seed=3,
    )


def test_generation_reports_each_finished_shard_in_order_and_the_values_do_not_change() -> None:
    seen: list[tuple[int, int]] = []
    paths, _ = generate(request(), 1, lambda done, total: seen.append((done, total)))
    assert seen == [(1, 3), (2, 3), (3, 3)] and len(shard_sizes(600)) == 3
    quiet, _ = generate(request(), 1)
    assert np.array_equal(paths, quiet)


def test_generation_on_real_worker_processes_gives_the_same_paths_and_the_same_reports() -> None:
    seen: list[tuple[int, int]] = []
    parallel, _ = generate(request(), 2, lambda done, total: seen.append((done, total)))
    serial, _ = generate(request(), 1)
    assert np.array_equal(parallel, serial)
    assert seen == [(1, 3), (2, 3), (3, 3)]
