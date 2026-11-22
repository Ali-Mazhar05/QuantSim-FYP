"""The result of a calibration fit (K5, Lane C guide §7.1).

A fit never raises on bad data (C-FR-04): it returns a :class:`FitResult` whose
``refusal_reason`` says why, starting with one of the codes below and a colon, for
example ``"insufficient_history: GBM needs at least 60 observations, got 45"``. Lane B
maps the code to a 422 problem.
"""

import math
from dataclasses import dataclass
from typing import Literal

__all__ = [
    "REFUSAL_CODES",
    "REFUSAL_CONSTANT_SERIES",
    "REFUSAL_INSUFFICIENT_HISTORY",
    "REFUSAL_INVALID_INPUT",
    "REFUSAL_NOT_MEAN_REVERTING",
    "REFUSAL_NUMERICAL_FAILURE",
    "FitResult",
    "Model",
    "aic",
    "refusal_code",
    "refused",
]

Model = Literal["gbm", "ou", "merton"]

REFUSAL_INVALID_INPUT = "invalid_input"
"""Not one-dimensional, not numbers, NaN or infinity, or a bad ``dt``/option."""
REFUSAL_INSUFFICIENT_HISTORY = "insufficient_history"
"""Fewer observations than the model needs (GBM and OU 60, Merton 500)."""
REFUSAL_CONSTANT_SERIES = "constant_series"
"""The series does not move, so no volatility can be estimated."""
REFUSAL_NOT_MEAN_REVERTING = "not_mean_reverting"
"""OU only: the ADF test does not reject a unit root, or the AR(1) slope is outside (0, 1)."""
REFUSAL_NUMERICAL_FAILURE = "numerical_failure"
"""An estimate could not be computed (a non-finite result or a numerical error)."""

REFUSAL_CODES = frozenset(
    {
        REFUSAL_INVALID_INPUT,
        REFUSAL_INSUFFICIENT_HISTORY,
        REFUSAL_CONSTANT_SERIES,
        REFUSAL_NOT_MEAN_REVERTING,
        REFUSAL_NUMERICAL_FAILURE,
    }
)


@dataclass(frozen=True)
class FitResult:
    """A fitted model, or a refusal.

    ``params`` and ``std_errors`` share keys: GBM ``mu, sigma``; OU ``kappa, theta,
    sigma`` (on log price, ``theta`` the long-run log level); Merton ``mu, sigma, lam,
    mu_j, sigma_j``. These are the parameter names of Lane B's path generators. A
    standard error is NaN where it cannot be estimated (a Merton parameter on a bound).
    ``aic`` is 2k - 2 log L. A refused result has empty ``params`` and ``std_errors``,
    NaN ``log_likelihood`` and ``aic``, and ``converged`` False.
    """

    model: Model
    params: dict[str, float]
    std_errors: dict[str, float]
    log_likelihood: float
    aic: float
    n_obs: int
    converged: bool
    refusal_reason: str | None = None

    @property
    def refused(self) -> bool:
        """True when the fit was refused (``refusal_reason`` is set)."""
        return self.refusal_reason is not None


def aic(k: int, log_likelihood: float) -> float:
    """Akaike information criterion 2k - 2 log L (Akaike 1974)."""
    return 2.0 * k - 2.0 * log_likelihood


def refused(model: Model, n_obs: int, code: str, message: str) -> FitResult:
    """A refusal with ``code`` (one of :data:`REFUSAL_CODES`) and a readable message."""
    if code not in REFUSAL_CODES:
        raise ValueError(f"unknown refusal code {code!r}")
    return FitResult(
        model=model,
        params={},
        std_errors={},
        log_likelihood=math.nan,
        aic=math.nan,
        n_obs=n_obs,
        converged=False,
        refusal_reason=f"{code}: {message}",
    )


def refusal_code(result: FitResult) -> str | None:
    """The refusal code of ``result`` (the text before the first colon), or None."""
    if result.refusal_reason is None:
        return None
    return result.refusal_reason.split(":", 1)[0]
