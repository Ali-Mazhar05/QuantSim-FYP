"""Input handling shared by the three fits."""

import math
from collections.abc import Callable

import numpy as np
from numpy.typing import NDArray

from qs_quant._validation import Series, as_series
from qs_quant.calibration.result import (
    REFUSAL_INVALID_INPUT,
    REFUSAL_NUMERICAL_FAILURE,
    FitResult,
    Model,
    refused,
)

__all__ = ["guarded", "log_returns", "prepare"]


def log_returns(prices: Series) -> NDArray[np.float64]:
    """Log returns r_t = ln(S_t / S_{t-1}) of a price series, the input of
    :func:`~qs_quant.calibration.fit_gbm` and :func:`~qs_quant.calibration.fit_merton`.

    Every price must be positive. Fewer than two prices give an empty array.
    """
    p = as_series(prices, "prices")
    if np.any(p <= 0):
        raise ValueError("prices must all be positive to take logs")
    return np.diff(np.log(p))


def prepare(x: Series, name: str, *, model: Model, dt: float) -> NDArray[np.float64] | FitResult:
    """``x`` as a finite 1-D float array, or an ``invalid_input`` refusal."""
    if isinstance(dt, bool) or not isinstance(dt, int | float) or not math.isfinite(dt):
        return refused(model, 0, REFUSAL_INVALID_INPUT, f"dt must be a finite number, got {dt!r}")
    if not 0 < dt <= 1:
        return refused(model, 0, REFUSAL_INVALID_INPUT, f"dt must be in (0, 1], got {dt}")
    try:
        return as_series(x, name)
    except ValueError as exc:
        return refused(model, 0, REFUSAL_INVALID_INPUT, str(exc))


def _all_finite(result: FitResult) -> bool:
    return math.isfinite(result.log_likelihood) and all(
        math.isfinite(v) for v in result.params.values()
    )


def guarded(model: Model, n_obs: int, fit: Callable[[], FitResult]) -> FitResult:
    """Run a fit body so that it never raises on bad data (C-FR-04).

    Floating-point warnings are silenced inside (``np.errstate``, local to this call)
    and the result is checked instead: a numerical error or a non-finite estimate
    becomes a ``numerical_failure`` refusal. Standard errors may be NaN on purpose.
    """
    try:
        with np.errstate(all="ignore"):
            result = fit()
    except (ValueError, ArithmeticError, np.linalg.LinAlgError) as exc:
        return refused(model, n_obs, REFUSAL_NUMERICAL_FAILURE, f"{type(exc).__name__}: {exc}")
    if not result.refused and not _all_finite(result):
        return refused(model, n_obs, REFUSAL_NUMERICAL_FAILURE, "an estimate is not finite")
    return result
