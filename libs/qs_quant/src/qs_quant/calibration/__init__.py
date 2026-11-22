"""Model calibration (K5): GBM, Ornstein-Uhlenbeck and Merton jump-diffusion fits.

Needs the ``calibration`` extra (SciPy and statsmodels): depend on
``qs-quant[calibration]``. Formulas: Lane C guide §7.1-7.4. Every fit returns a
:class:`FitResult` and never raises on bad data; a refusal carries a reason that starts
with one of the ``REFUSAL_*`` codes.
"""

from qs_quant.calibration._common import log_returns
from qs_quant.calibration.gbm import MIN_OBS_GBM, fit_gbm
from qs_quant.calibration.merton import MIN_OBS_MERTON, fit_merton
from qs_quant.calibration.ou import ADF_LEVEL, MIN_OBS_OU, fit_ou
from qs_quant.calibration.result import (
    REFUSAL_CODES,
    REFUSAL_CONSTANT_SERIES,
    REFUSAL_INSUFFICIENT_HISTORY,
    REFUSAL_INVALID_INPUT,
    REFUSAL_NOT_MEAN_REVERTING,
    REFUSAL_NUMERICAL_FAILURE,
    FitResult,
    refusal_code,
)

__all__ = [
    "ADF_LEVEL",
    "MIN_OBS_GBM",
    "MIN_OBS_MERTON",
    "MIN_OBS_OU",
    "REFUSAL_CODES",
    "REFUSAL_CONSTANT_SERIES",
    "REFUSAL_INSUFFICIENT_HISTORY",
    "REFUSAL_INVALID_INPUT",
    "REFUSAL_NOT_MEAN_REVERTING",
    "REFUSAL_NUMERICAL_FAILURE",
    "FitResult",
    "fit_gbm",
    "fit_merton",
    "fit_ou",
    "log_returns",
    "refusal_code",
]
