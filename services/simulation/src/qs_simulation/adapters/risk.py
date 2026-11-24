"""VaR and CVaR for the run statistics (B16): K6 when it is installed, else Lane C's formula.

K6 (``qs_quant.metrics.var_cvar``, Lane C) owns the definition. Its formula is fully specified
in the mathematical specification (section 7.6), so until K6 is installed that formula is used, and
a test holds the two equal the day K6 arrives (tracker I-04). The version is recorded so a result
says which one made it.
"""

import importlib
from collections.abc import Callable
from typing import Any

import numpy as np

MIN_RETURNS = 20


def reference_var_cvar(returns: Any, alpha: float = 0.95) -> tuple[float, float]:
    """``q = quantile(R, 1 - alpha)`` (linear); ``VaR = -q``; ``CVaR = -mean(R | R <= q)``.
    Both are positive losses and CVaR is at least VaR by construction."""
    values = np.asarray(returns, dtype=np.float64)
    if values.ndim != 1 or values.size < MIN_RETURNS:
        raise ValueError(f"at least {MIN_RETURNS} returns are needed")
    if not 0.0 < alpha < 1.0:
        raise ValueError("alpha must lie between 0 and 1")
    q = float(np.quantile(values, 1.0 - alpha))
    return -q, -float(values[values <= q].mean())


class ReferenceRisk:
    version = "reference-7.6"

    def var_cvar(self, returns: Any, alpha: float = 0.95) -> tuple[float, float]:
        return reference_var_cvar(returns, alpha)


class QuantRisk:
    """K6's ``var_cvar``, imported when the library is installed."""

    def __init__(self, module: str = "qs_quant.metrics") -> None:
        self._module_name = module
        self._function: Callable[..., tuple[float, float]] | None = None
        try:
            found = getattr(importlib.import_module(module), "var_cvar", None)
        except ImportError:
            found = None
        self._function = found if callable(found) else None

    @property
    def available(self) -> bool:
        return self._function is not None

    @property
    def version(self) -> str:
        root = importlib.import_module(self._module_name.split(".")[0])
        return str(getattr(root, "__version__", "unknown"))

    def var_cvar(self, returns: Any, alpha: float = 0.95) -> tuple[float, float]:
        if self._function is None:
            raise RuntimeError("qs_quant.metrics.var_cvar is not installed")
        var, cvar = self._function(np.asarray(returns, dtype=np.float64), alpha)
        return float(var), float(cvar)


def default_risk() -> "QuantRisk | ReferenceRisk":
    """K6 when it is installed, else the specification's formula."""
    quant = QuantRisk()
    return quant if quant.available else ReferenceRisk()
