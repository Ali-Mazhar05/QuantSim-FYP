"""Input checks shared by every qs_quant function."""

from collections.abc import Sequence
from decimal import Decimal

import numpy as np
from numpy.typing import ArrayLike, NDArray

Series = ArrayLike | Sequence[Decimal]
"""What every public function accepts: anything NumPy reads as numbers (arrays, lists of
floats) plus sequences of ``Decimal``, which the services use for money."""


def as_series(x: Series, name: str, *, min_len: int = 0) -> NDArray[np.float64]:
    """``x`` as a 1-D float64 array of finite values, or ``ValueError`` naming ``name``."""
    try:
        arr = np.asarray(x, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numbers: {exc}") from exc
    if arr.ndim != 1:
        raise ValueError(f"{name} must be one-dimensional, got shape {arr.shape}")
    if arr.size < min_len:
        raise ValueError(f"{name} needs at least {min_len} points, got {arr.size}")
    if not np.all(np.isfinite(arr)):
        raise ValueError(f"{name} contains NaN or infinite values")
    return arr


def check_periods(periods: int) -> None:
    """Annualisation needs a positive number of periods per year."""
    if periods <= 0:
        raise ValueError(f"periods must be positive, got {periods}")
