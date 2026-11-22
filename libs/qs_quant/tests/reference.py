"""Exact rational reference implementations of the K6 formulas (tests only).

The library is checked against these, so the expected numbers never come from NumPy:
every sum, mean and ratio is exact, and a float square root is taken only at the end.
"""

import math
from fractions import Fraction
from itertools import pairwise


def F(x: float | int | str) -> Fraction:
    """An exact fraction of a decimal literal (via str, so 0.1 means 1/10)."""
    return Fraction(str(x))


def returns(values: list[Fraction]) -> list[Fraction]:
    return [b / a - 1 for a, b in pairwise(values)]


def mean(xs: list[Fraction]) -> Fraction:
    return sum(xs, Fraction(0)) / len(xs)


def var_ddof1(xs: list[Fraction]) -> Fraction:
    m = mean(xs)
    return sum(((x - m) ** 2 for x in xs), Fraction(0)) / (len(xs) - 1)


def total_return(values: list[Fraction]) -> Fraction:
    return values[-1] / values[0] - 1


def volatility(rs: list[Fraction], periods: int = 252) -> float:
    return math.sqrt(var_ddof1(rs) * periods)


def sharpe(rs: list[Fraction], rf: Fraction = Fraction(0), periods: int = 252) -> float:
    ex = [r - rf / periods for r in rs]
    return float(mean(ex)) / math.sqrt(var_ddof1(ex)) * math.sqrt(periods)


def max_drawdown(values: list[Fraction]) -> Fraction:
    peak, worst = values[0], Fraction(0)
    for v in values:
        peak = max(peak, v)
        worst = max(worst, 1 - v / peak)
    return worst


def turnover(fills: list[Fraction], values: list[Fraction]) -> Fraction:
    return sum((abs(f) for f in fills), Fraction(0)) / mean(values)


def quantile_type7(xs: list[Fraction], p: Fraction) -> Fraction:
    s = sorted(xs)
    h = (len(s) - 1) * p
    lo = math.floor(h)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (h - lo) * (s[hi] - s[lo])


def var_cvar(rs: list[Fraction], alpha: Fraction) -> tuple[Fraction, Fraction]:
    q = quantile_type7(rs, 1 - alpha)
    tail = [r for r in rs if r <= q]
    return -q, -mean(tail)
