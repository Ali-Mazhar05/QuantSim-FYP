"""Calibration inputs and outputs, as pure values and functions (B15).

A calibration fits a model to the adjusted closes of one instrument over a window. Nothing here
fetches prices or fits a model: those are ports (``qs_simulation.ports``), so this module can be
tested alone and the fit itself stays in ``qs_quant`` (K5), which Lane C owns.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from itertools import pairwise
from typing import Literal

import numpy as np
import xxhash

MIN_SESSIONS = 60  # fewer closes than this is refused before any model is asked (B-FR-09)
PRICE_SCALE = Decimal("1E-10")
FINGERPRINT_PREFIX = "xxh3:"

Model = Literal["gbm", "ou", "merton"]

# problem types a refusal can carry; the page shows the reason, a client switches on the type
INSUFFICIENT_HISTORY = "insufficient_history"
FIT_REFUSED = "fit_refused"
INSTRUMENT_NOT_FOUND = "instrument_not_found"
MISSING_ADJUSTED_PRICES = "missing_adjusted_prices"
INVALID_PRICES = "invalid_prices"


class CalibrationRefused(Exception):
    """The calibration cannot be made from this data. A refusal is a result, not a fault: asking
    again with the same data gives the same answer, so the job is not retried."""

    def __init__(self, code: str, reason: str) -> None:
        self.code = code
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class PricePoint:
    """One adjusted close and the revision of the bar it came from."""

    session_date: date
    adj_close: Decimal
    revision: int


@dataclass(frozen=True)
class FitResult:
    """What a fit returns (the interface of ``qs_quant.calibration.FitResult``, K5): a refusal is
    reported in ``refusal_reason`` instead of raising."""

    model: Model
    params: dict[str, float]
    std_errors: dict[str, float]
    log_likelihood: float
    aic: float
    n_obs: int
    converged: bool
    refusal_reason: str | None = None


def ordered(points: Sequence[PricePoint]) -> list[PricePoint]:
    """The window in session order; a session twice is a fault in the source and is refused."""
    result = sorted(points, key=lambda p: p.session_date)
    for before, after in pairwise(result):
        if before.session_date == after.session_date:
            raise CalibrationRefused(
                INVALID_PRICES, f"two closes for the session {after.session_date.isoformat()}"
            )
    return result


def check_window(points: Sequence[PricePoint]) -> list[PricePoint]:
    """The ordered window, or the reason it cannot be calibrated: too short, or a close that has no
    logarithm. Runs before any model is asked."""
    result = ordered(points)
    if len(result) < MIN_SESSIONS:
        raise CalibrationRefused(
            INSUFFICIENT_HISTORY,
            f"{len(result)} sessions in the window; at least {MIN_SESSIONS} are needed",
        )
    for p in result:
        if not p.adj_close.is_finite() or p.adj_close <= 0:
            raise CalibrationRefused(
                INVALID_PRICES,
                f"the adjusted close on {p.session_date.isoformat()} is not a positive number",
            )
    return result


def input_fingerprint(points: Sequence[PricePoint]) -> str:
    """Identifies the exact prices a fit used: xxh3 over the ordered ``(session_date, adj_close,
    revision)``. Closes are written at one scale, so the value does not depend on how the source
    formatted them; it changes when a close is restated or a revision lands."""
    digest = xxhash.xxh3_128()
    for p in ordered(points):
        close = format(p.adj_close.quantize(PRICE_SCALE), "f")
        digest.update(f"{p.session_date.isoformat()}|{close}|{p.revision}\n".encode())
    return FINGERPRINT_PREFIX + digest.hexdigest()


def log_prices(points: Sequence[PricePoint]) -> np.ndarray:
    """ln of the adjusted closes in session order (the input of ``fit_ou``)."""
    return np.log(np.array([float(p.adj_close) for p in ordered(points)], dtype=np.float64))


def log_returns(points: Sequence[PricePoint]) -> np.ndarray:
    """ln(S_t / S_{t-1}) in session order (the input of ``fit_gbm`` and ``fit_merton``)."""
    return np.diff(log_prices(points))
