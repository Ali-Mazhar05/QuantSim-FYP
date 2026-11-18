"""B-FR-10, B-FR-11, B-NFR-04, B-NFR-05, B-NFR-06: reproducible, worker-invariant, correlated."""

from dataclasses import replace
from typing import Any

import numpy as np
import pytest

from qs_simulation.domain.sharding import (
    SHARD_SIZE,
    PathRequest,
    generate,
    generate_shard,
    shard_sizes,
    shard_streams,
)
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
GBM = {"mu": np.array([0.08, -0.03, 0.15, 0.05]), "sigma": np.array([0.20, 0.35, 0.60, 0.30])}
OU = {
    "kappa": np.array([3.0, 8.0, 1.5, 4.0]),
    "theta": np.log(np.array([110.0, 45.0, 250.0, 22.0])),
    "sigma": np.array([0.25, 0.40, 0.30, 0.35]),
}
MERTON = GBM | {
    "lam": np.array([3.0, 1.0, 5.0, 2.0]),
    "mu_j": np.array([-0.05, 0.02, -0.08, 0.0]),
    "sigma_j": np.array([0.08, 0.05, 0.10, 0.06]),
}
PARAMS = {"gbm": GBM, "ou": OU, "merton": MERTON}


def request(model: str = "gbm", paths: int = 1_000, steps: int = 20, seed: int = 42) -> PathRequest:
    return PathRequest(
        model=model,  # type: ignore[arg-type]
        s0=S0,
        params=PARAMS[model],
        correlation=RHO,
        n_paths=paths,
        n_steps=steps,
        seed=seed,
    )


def test_shards_are_fixed_size_with_a_remainder() -> None:
    assert SHARD_SIZE == 250
    assert shard_sizes(600) == [250, 250, 100]
    assert shard_sizes(250) == [250] and shard_sizes(1) == [1]
    with pytest.raises(ValueError, match="n_paths"):
        shard_sizes(0)


def test_the_jump_streams_never_change_gbm_or_ou_output() -> None:
    gbm, _ = generate(request("gbm", seed=3))
    merton_without_jumps = request("merton", seed=3)
    zero = {**merton_without_jumps.params, "lam": np.zeros(4)}
    no_jumps, _ = generate(replace(merton_without_jumps, params=zero))
    np.testing.assert_allclose(no_jumps, gbm, rtol=1e-12)  # same normals, so the same paths


@pytest.mark.parametrize("model", ["gbm", "ou", "merton"])
def test_one_two_and_four_workers_give_identical_paths(model: str) -> None:
    req = request(model)
    one, _ = generate(req, workers=1)
    two, _ = generate(req, workers=2)
    four, _ = generate(req, workers=4)
    assert one.shape == (1_000, 20, 4)
    np.testing.assert_array_equal(one, two)
    np.testing.assert_array_equal(one, four)


def test_a_shard_depends_only_on_the_seed_and_its_index() -> None:
    small = generate_shard(request(paths=1_000), 1)
    large = generate_shard(request(paths=5_000), 1)  # more shards in the run, same shard 1
    np.testing.assert_array_equal(small, large)
    first = shard_streams(42, 3)[0].standard_normal(5)
    np.testing.assert_array_equal(first, shard_streams(42, 3)[0].standard_normal(5))
    assert not np.array_equal(first, shard_streams(42, 4)[0].standard_normal(5))
    assert not np.array_equal(first, shard_streams(43, 3)[0].standard_normal(5))


def test_same_seed_repeats_and_another_seed_differs() -> None:
    a, _ = generate(request(seed=7))
    b, _ = generate(request(seed=7))
    c, _ = generate(request(seed=8))
    np.testing.assert_array_equal(a, b)
    assert not np.array_equal(a, c)


def test_generated_paths_recover_the_target_correlation() -> None:
    paths, record = generate(request(paths=20_000, steps=21))
    log_returns = np.diff(
        np.log(np.concatenate([np.broadcast_to(S0, (20_000, 1, 4)), paths], 1)), axis=1
    )
    sample = np.corrcoef(log_returns.reshape(-1, 4), rowvar=False)
    assert np.abs(sample - RHO).max() <= 0.02
    assert not record.applied


def test_terminal_moments_hold_through_the_full_pipeline() -> None:
    steps = 252
    paths, _ = generate(request(paths=20_000, steps=steps, seed=99))
    horizon = steps / 252
    terminal = np.log(paths[:, -1, :])
    mean = np.log(S0) + (GBM["mu"] - 0.5 * GBM["sigma"] ** 2) * horizon
    assert np.all(np.abs(z_mean(terminal, mean)) < 3)
    assert np.all(np.abs(z_variance(terminal, GBM["sigma"] ** 2 * horizon)) < 3)


def test_a_non_psd_correlation_still_generates_and_the_repair_is_recorded() -> None:
    bad = np.array([[1.0, 0.9, -0.9], [0.9, 1.0, 0.9], [-0.9, 0.9, 1.0]])
    req = PathRequest("gbm", S0[:3], {k: v[:3] for k, v in GBM.items()}, bad, 300, 10, seed=5)
    paths, record = generate(req)
    assert record.applied and record.frobenius_change > 0
    assert np.all(np.isfinite(paths)) and np.all(paths > 0)


@pytest.mark.parametrize(
    ("change", "words"),
    [
        ({"n_paths": 0}, "at least 1"),
        ({"seed": -1}, "seed"),
        ({"model": "heston"}, "model must be one of"),
        ({"params": {"mu": GBM["mu"]}}, "missing parameters for gbm: sigma"),
        ({"correlation": np.eye(3)}, "one row per instrument"),
    ],
)
def test_a_bad_request_is_refused_naming_the_field(change: dict[str, Any], words: str) -> None:
    with pytest.raises(ValueError, match=words):
        generate(replace(request(), **change))


def test_workers_must_be_positive() -> None:
    with pytest.raises(ValueError, match="workers"):
        generate(request(), workers=0)
