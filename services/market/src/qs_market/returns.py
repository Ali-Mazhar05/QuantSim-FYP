"""Returns and volatility (FR-MKT-003), computed once here and stored, so no other
service computes them differently.

log return       r_t = ln(P_t / P_{t-1})
volatility (n)   sample standard deviation of the last n log returns x sqrt(252)

Raw returns use the close; adjusted returns use the split- and dividend-adjusted close,
and volatility is computed from adjusted returns so a split does not look like a crash.
"""

import math
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

TRADING_DAYS = 252
WINDOWS = (20, 60)


@dataclass(frozen=True)
class PricePoint:
    session_date: date
    close: Decimal
    adj_close: Decimal | None


@dataclass(frozen=True)
class ReturnPoint:
    session_date: date
    log_return: float | None
    adj_log_return: float | None
    vol_20d: float | None
    vol_60d: float | None


def _log_return(current: Decimal | None, previous: Decimal | None) -> float | None:
    if current is None or previous is None or current <= 0 or previous <= 0:
        return None
    return math.log(float(current) / float(previous))


def compute(points: Sequence[PricePoint]) -> list[ReturnPoint]:
    """Returns and rolling volatility for consecutive sessions, oldest first."""
    result: list[ReturnPoint] = []
    adjusted: list[float] = []
    for i, point in enumerate(points):
        previous = points[i - 1] if i else None
        raw = _log_return(point.close, previous.close if previous else None)
        adj = _log_return(
            point.adj_close if point.adj_close is not None else point.close,
            (previous.adj_close if previous.adj_close is not None else previous.close)
            if previous
            else None,
        )
        if adj is not None:
            adjusted.append(adj)
        vols = {
            n: statistics.stdev(adjusted[-n:]) * math.sqrt(TRADING_DAYS)
            if adj is not None and len(adjusted) >= n
            else None
            for n in WINDOWS
        }
        result.append(
            ReturnPoint(
                session_date=point.session_date,
                log_return=raw,
                adj_log_return=adj,
                vol_20d=vols[20],
                vol_60d=vols[60],
            )
        )
    return result
