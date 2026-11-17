"""Reproducible generation: fixed shards, each seeded only by (seed, shard index) (ADR 02).

The output depends on the request alone, never on how many workers run it or in what order:
shard ``k`` always uses the same three random streams (normals, Poisson counts, jump sizes).
"""

from collections.abc import Mapping
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from typing import Literal

import numpy as np

from qs_simulation.domain.correlation import (
    Array,
    RepairRecord,
    correlate,
    correlation_factor,
)
from qs_simulation.domain.generators import simulate_gbm, simulate_ou

SHARD_SIZE = 250
Model = Literal["gbm", "ou"]
REQUIRED: dict[str, tuple[str, ...]] = {"gbm": ("mu", "sigma"), "ou": ("kappa", "theta", "sigma")}


@dataclass(frozen=True, eq=False)
class PathRequest:
    """Everything that defines a run's paths. The instrument order is part of the request."""

    model: Model
    s0: Array
    params: Mapping[str, Array]
    correlation: Array
    n_paths: int
    n_steps: int
    seed: int
    dt: float = 1 / 252

    def validate(self) -> None:
        if self.model not in REQUIRED:
            raise ValueError(f"model must be one of {sorted(REQUIRED)}")
        if self.n_paths < 1 or self.n_steps < 1:
            raise ValueError("n_paths and n_steps must be at least 1")
        if self.seed < 0:
            raise ValueError("seed must not be negative")
        n = self.s0.shape[0] if self.s0.ndim == 1 else -1
        if n < 1 or self.correlation.shape != (n, n):
            raise ValueError("correlation must be square with one row per instrument")
        missing = [name for name in REQUIRED[self.model] if name not in self.params]
        if missing:
            raise ValueError(f"missing parameters for {self.model}: {', '.join(missing)}")


def shard_sizes(n_paths: int) -> list[int]:
    """Full shards of ``SHARD_SIZE`` paths, then the remainder."""
    if n_paths < 1:
        raise ValueError("n_paths must be at least 1")
    full, rest = divmod(n_paths, SHARD_SIZE)
    return [SHARD_SIZE] * full + ([rest] if rest else [])


def shard_streams(
    seed: int, shard: int
) -> tuple[np.random.Generator, np.random.Generator, np.random.Generator]:
    """Normals, Poisson counts and jump sizes for one shard; a pure function of the arguments."""
    streams = [
        np.random.Generator(np.random.PCG64(np.random.SeedSequence(seed, spawn_key=(shard, i))))
        for i in range(3)
    ]
    return streams[0], streams[1], streams[2]


def generate_shard(request: PathRequest, shard: int) -> Array:
    """Paths of shape (shard paths, steps, instruments) for one shard of the request."""
    request.validate()
    size = shard_sizes(request.n_paths)[shard]
    n = request.s0.shape[0]
    normals, _, _ = shard_streams(request.seed, shard)
    factor, _ = correlation_factor(request.correlation)
    shocks = correlate(normals.standard_normal((size, request.n_steps, n)), factor)
    p = request.params
    if request.model == "gbm":
        return simulate_gbm(request.s0, p["mu"], p["sigma"], request.dt, shocks)
    return simulate_ou(request.s0, p["kappa"], p["theta"], p["sigma"], request.dt, shocks)


def _run_shard(job: tuple[PathRequest, int]) -> Array:
    return generate_shard(*job)


def generate(request: PathRequest, workers: int = 1) -> tuple[Array, RepairRecord]:
    """All paths, shape (paths, steps, instruments), and the correlation repair record.

    ``workers`` changes only how fast the shards are computed, never their values.
    """
    request.validate()
    if workers < 1:
        raise ValueError("workers must be at least 1")
    _, record = correlation_factor(request.correlation)
    jobs = [(request, k) for k in range(len(shard_sizes(request.n_paths)))]
    if workers == 1:
        parts = [_run_shard(job) for job in jobs]
    else:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            parts = list(pool.map(_run_shard, jobs))
    return np.concatenate(parts, axis=0), record
