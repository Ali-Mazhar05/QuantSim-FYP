"""Risk statistics (K6, C-FR-06; Lane C guide §7.6)."""

import numpy as np

from qs_quant._validation import Series, as_series

__all__ = ["MIN_RETURNS", "var_cvar"]

MIN_RETURNS = 20
"""The fewest returns var_cvar accepts."""


def var_cvar(returns: Series, alpha: float = 0.95) -> tuple[float, float]:
    """Historical Value at Risk and Conditional VaR at confidence ``alpha``, as positive losses.

    q = quantile(R, 1 - alpha) with linear interpolation (Hyndman and Fan 1996, type 7;
    numpy ``method="linear"``); VaR = -q; CVaR = -mean(R | R <= q).

    References: Jorion, P. (2007), Value at Risk, 3rd ed., McGraw-Hill; Acerbi, C. and
    Tasche, D. (2002), "On the coherence of expected shortfall", Journal of Banking and
    Finance 26(7), 1487-1503.

    CVaR >= VaR by construction. The result is clamped so that floating-point rounding
    in the tail mean cannot break this by one ulp. VaR is negative when even the 1 - alpha
    quantile is a gain. Needs at least 20 returns and 0 < alpha < 1.
    """
    if not 0.0 < alpha < 1.0:
        raise ValueError(f"alpha must be in (0, 1), got {alpha}")
    r = as_series(returns, "returns")
    if r.size < MIN_RETURNS:
        raise ValueError(f"var_cvar needs at least {MIN_RETURNS} returns, got {r.size}")
    q = float(np.quantile(r, 1.0 - alpha, method="linear"))
    tail = r[r <= q]  # never empty: min(r) <= q
    var = -q
    cvar = max(float(-np.mean(tail)), var)
    return var, cvar
