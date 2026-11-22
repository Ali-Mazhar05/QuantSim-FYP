"""Input checks shared by the generators, so a bad request fails loudly and names the field."""

import numpy as np
from numpy.typing import NDArray

Array = NDArray[np.float64]


def check_shocks(shocks: Array, dt: float) -> int:
    """Validate the shock array and the step; return the number of instruments."""
    if shocks.ndim != 3:
        raise ValueError("shocks must have shape (paths, steps, instruments)")
    if min(shocks.shape) == 0:
        raise ValueError("shocks must not be empty")
    if not np.all(np.isfinite(shocks)):
        raise ValueError("shocks must be finite")
    if not (np.isfinite(dt) and dt > 0):
        raise ValueError("dt must be positive")
    return int(shocks.shape[2])


def check_param(
    name: str,
    values: Array,
    n_instruments: int,
    *,
    positive: bool = False,
    non_negative: bool = False,
) -> None:
    """One value per instrument, finite, and positive or non-negative where the model needs it."""
    if values.shape != (n_instruments,):
        raise ValueError(f"{name} must have one value per instrument ({n_instruments})")
    if not np.all(np.isfinite(values)):
        raise ValueError(f"{name} must be finite")
    if positive and not np.all(values > 0):
        raise ValueError(f"{name} must be positive")
    if non_negative and not np.all(values >= 0):
        raise ValueError(f"{name} must not be negative")


def check_vol_scale(vol_scale: Array | None, n_steps: int) -> None:
    """A volatility multiplier for each step (a stress scenario): finite and positive."""
    if vol_scale is None:
        return
    if vol_scale.shape != (n_steps,):
        raise ValueError(f"vol_scale must have one value per step ({n_steps})")
    if not np.all(np.isfinite(vol_scale)) or not np.all(vol_scale > 0):
        raise ValueError("vol_scale must be finite and positive")
