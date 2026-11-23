"""The fitting code behind the ``Calibrator`` port (B15).

The fits live in ``qs_quant.calibration`` (K5, Lane C): ``fit_gbm`` and ``fit_merton`` take the log
returns, ``fit_ou`` the log prices, and each returns a ``FitResult`` that carries a refusal reason
instead of raising. Until K5 is installed, or for a model it has not delivered, this adapter says
so (``CalibratorUnavailable``) and the API answers 501, instead of faking a fit.
"""

import importlib
from collections.abc import Callable
from typing import Any

from qs_simulation.domain.calibration import (
    FitResult,
    Model,
    PricePoint,
    log_prices,
    log_returns,
)
from qs_simulation.ports import CalibratorUnavailable

DT = 1 / 252  # one session, in years (Lane C's convention for every fit)
FIT_FUNCTIONS: dict[Model, str] = {"gbm": "fit_gbm", "ou": "fit_ou", "merton": "fit_merton"}


class QuantCalibrator:
    def __init__(self, module: str = "qs_quant.calibration") -> None:
        self._module_name = module
        self._module: Any = None
        try:
            self._module = importlib.import_module(module)
        except ImportError:
            self._module = None

    @property
    def version(self) -> str:
        if self._module is None:
            return "unavailable"
        root = importlib.import_module(self._module_name.split(".")[0])
        return str(getattr(root, "__version__", "unknown"))

    def _function(self, model: Model) -> Callable[..., Any] | None:
        if self._module is None:
            return None
        found = getattr(self._module, FIT_FUNCTIONS[model], None)
        return found if callable(found) else None

    def supports(self, model: Model) -> bool:
        return self._function(model) is not None

    def fit(self, model: Model, points: list[PricePoint]) -> FitResult:
        function = self._function(model)
        if function is None:
            raise CalibratorUnavailable(model)
        data = log_prices(points) if model == "ou" else log_returns(points)
        result = function(data, DT)
        return FitResult(
            model=model,
            params={k: float(v) for k, v in result.params.items()},
            std_errors={k: float(v) for k, v in result.std_errors.items()},
            log_likelihood=float(result.log_likelihood),
            aic=float(result.aic),
            n_obs=int(result.n_obs),
            converged=bool(result.converged),
            refusal_reason=result.refusal_reason,
        )
