"""Correlation structure for the synthetic market (ADR 02): validate, repair, factorise."""

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

Array = NDArray[np.float64]

EIGENVALUE_FLOOR = 1e-8


@dataclass(frozen=True)
class RepairRecord:
    """What the repair did, stored on the run so a result can be audited."""

    applied: bool
    min_eigenvalue_before: float
    frobenius_change: float


def _check_correlation(rho: Array) -> None:
    if rho.ndim != 2 or rho.shape[0] != rho.shape[1] or rho.shape[0] == 0:
        raise ValueError("correlation must be a non-empty square matrix")
    if not np.all(np.isfinite(rho)):
        raise ValueError("correlation must be finite")
    if not np.allclose(rho, rho.T, atol=1e-10):
        raise ValueError("correlation must be symmetric")
    if not np.allclose(np.diag(rho), 1.0, atol=1e-8):
        raise ValueError("correlation must have a unit diagonal")
    if np.any(np.abs(rho) > 1.0 + 1e-12):
        raise ValueError("correlation entries must lie in [-1, 1]")


def repair_psd(rho: Array, floor: float = EIGENVALUE_FLOOR) -> tuple[Array, RepairRecord]:
    """Return a positive definite correlation matrix close to ``rho``, and what changed.

    A matrix whose smallest eigenvalue is at least ``floor`` is returned unchanged (made exactly
    symmetric). Otherwise eigenvalues below the floor are raised to it and the result is rescaled
    to a unit diagonal, which keeps it positive definite.
    """
    _check_correlation(rho)
    sym: Array = (rho + rho.T) / 2.0
    values, vectors = np.linalg.eigh(sym)
    smallest = float(values.min())
    if smallest >= floor:
        return sym, RepairRecord(False, smallest, 0.0)
    rebuilt = (vectors * np.clip(values, floor, None)) @ vectors.T
    scale = np.sqrt(np.diag(rebuilt))
    fixed: Array = rebuilt / np.outer(scale, scale)
    fixed = (fixed + fixed.T) / 2.0
    return fixed, RepairRecord(True, smallest, float(np.linalg.norm(fixed - sym)))


def correlation_factor(rho: Array) -> tuple[Array, RepairRecord]:
    """Lower-triangular ``L`` with ``L L^T = rho`` after any needed repair, plus the record."""
    repaired, record = repair_psd(rho)
    return np.linalg.cholesky(repaired), record


def correlate(independent: Array, factor: Array) -> Array:
    """Turn independent standard normals (last axis = instruments) into correlated ones."""
    out: Array = independent @ factor.T
    return out
