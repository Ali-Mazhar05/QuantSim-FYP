"""Portfolio performance metrics (K6, C-FR-05; Lane C guide §7.6).

``values`` is a portfolio value series V_0..V_T in time order; ``returns`` are simple
returns r_t = V_t / V_{t-1} - 1. Annualisation uses ``periods`` sessions per year (252).
Every function is pure and deterministic, returns a Python float, and is scale-free in V:
multiplying V (and fill notionals) by a constant leaves the result unchanged.
"""

import math

import numpy as np
from numpy.typing import NDArray

from qs_quant._validation import Series, as_series, check_periods

__all__ = [
    "annualised_volatility",
    "max_drawdown",
    "sharpe",
    "simple_returns",
    "total_return",
    "turnover",
]


def simple_returns(values: Series) -> NDArray[np.float64]:
    """Simple returns r_t = V_t / V_{t-1} - 1 for t = 1..T.

    Every value must be positive. Fewer than two values give an empty array.
    """
    v = as_series(values, "values")
    if np.any(v <= 0):
        raise ValueError("values must all be positive to form returns")
    if v.size < 2:
        return np.empty(0, dtype=np.float64)
    return v[1:] / v[:-1] - 1.0


def total_return(values: Series) -> float:
    """Total return V_T / V_0 - 1.

    Needs at least one value and V_0 > 0; a single value gives 0.0.
    Example: [100, 110, 99, 120] -> 0.2.
    """
    v = as_series(values, "values", min_len=1)
    if v[0] <= 0:
        raise ValueError(f"total_return needs V_0 > 0, got {v[0]}")
    return float(v[-1] / v[0] - 1.0)


def annualised_volatility(returns: Series, periods: int = 252) -> float | None:
    """Annualised volatility std(r, ddof=1) * sqrt(periods).

    None when there are fewer than two returns (the sample standard deviation is
    undefined).
    """
    check_periods(periods)
    r = as_series(returns, "returns")
    if r.size < 2:
        return None
    return float(np.std(r, ddof=1) * math.sqrt(periods))


def sharpe(returns: Series, rf_annual: float = 0.0, periods: int = 252) -> float | None:
    """Annualised Sharpe ratio mean(e) / std(e, ddof=1) * sqrt(periods), e = r - rf/periods.

    Reference: Sharpe, W. F. (1994), "The Sharpe Ratio", Journal of Portfolio Management
    21(1), 49-58.

    None when there are fewer than two returns or every return is identical. The second
    case is tested exactly with ``ptp == 0``, because rounding in the mean can make the
    floating-point standard deviation of a constant series slightly above zero, which
    would give a meaningless huge ratio.
    """
    check_periods(periods)
    if not math.isfinite(rf_annual):
        raise ValueError("rf_annual must be finite")
    r = as_series(returns, "returns")
    if r.size < 2 or np.ptp(r) == 0:
        return None
    excess = r - rf_annual / periods
    return float(np.mean(excess) / np.std(excess, ddof=1) * math.sqrt(periods))


def max_drawdown(values: Series) -> float:
    """Maximum drawdown max_t (1 - V_t / max_{s<=t} V_s), in [0, 1].

    Reference: Magdon-Ismail, M. and Atiya, A. F. (2004), "Maximum drawdown", Risk 17(10).

    0.0 for an empty or non-decreasing series. Values must be non-negative and V_0 > 0.
    Example: [100, 110, 99, 120] -> 1 - 99/110 = 0.1.
    """
    v = as_series(values, "values")
    if v.size == 0:
        return 0.0
    if np.any(v < 0) or v[0] <= 0:
        raise ValueError("max_drawdown needs non-negative values with V_0 > 0")
    peak = np.maximum.accumulate(v)
    return float(np.max(1.0 - v / peak))


def turnover(fill_notionals: Series, values: Series) -> float:
    """Turnover sum(|fill notional|) / mean(V).

    Fill notionals may be signed (sells negative); their absolute values are summed.
    0.0 with no fills. Needs at least one value and mean(V) > 0.
    """
    f = as_series(fill_notionals, "fill_notionals")
    v = as_series(values, "values", min_len=1)
    mean_v = float(np.mean(v))
    if mean_v <= 0:
        raise ValueError(f"turnover needs mean(values) > 0, got {mean_v}")
    if f.size == 0:
        return 0.0
    return float(np.sum(np.abs(f)) / mean_v)
