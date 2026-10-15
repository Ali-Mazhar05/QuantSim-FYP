"""Display intervals and chart metrics derived from stored daily bars (FYP FR-MKT-02,
FR-DASH-02, NFR-PERF-02).

Daily bars are the only stored series (FR-DB-04). A weekly, monthly or yearly candle is
computed on request from the daily bars inside the requested window:

    open = first open, high = maximum high, low = minimum low,
    close = last close, volume = sum of volumes.

A bucket is a calendar period of the exchange's own session date: an ISO week (Monday to
Sunday), a calendar month, a calendar year. Only sessions that exist are aggregated, so a
holiday-shortened week is simply a shorter bucket. The first and last bucket of a window
hold only the sessions inside it. A candle is labelled by its last session, the day its
close is struck, and also reports its first session.

The metrics follow the proof-of-concept's definitions:

    period return      last price / first price - 1
    annualised vol     sample standard deviation (n - 1) of the log returns of the
                       series, times the square root of the periods per year
    maximum drawdown   the lowest of (price - running peak) / running peak

Everything is ``Decimal``; no price or ratio passes through binary floating point. Where a
metric cannot be computed (too few observations, a zero denominator) it is ``None`` and the
reason is reported, never an invented number.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, localcontext
from itertools import pairwise
from typing import Literal

Interval = Literal["daily", "weekly", "monthly", "yearly"]
INTERVALS: tuple[str, ...] = ("daily", "weekly", "monthly", "yearly")

# Periods per year used to annualise volatility (the POC annualises daily series with 252)
PERIODS_PER_YEAR: dict[str, int] = {"daily": 252, "weekly": 52, "monthly": 12, "yearly": 1}

PRECISION = 40
RATIO_STEP = Decimal("0.000000000001")  # 12 places, as the stored returns


@dataclass(frozen=True)
class DailyBar:
    session_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    adj_close: Decimal | None = None


@dataclass(frozen=True)
class Candle:
    session_date: date  # the last session of the bucket
    period_start: date  # the first session of the bucket
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    adj_close: Decimal | None
    sessions: int


def bucket(session: date, interval: str) -> tuple[int, ...]:
    """The calendar period a session belongs to."""
    if interval == "daily":
        return (session.year, session.month, session.day)
    if interval == "weekly":
        iso = session.isocalendar()
        return (iso.year, iso.week)
    if interval == "monthly":
        return (session.year, session.month)
    if interval == "yearly":
        return (session.year,)
    raise ValueError(f"unknown interval {interval!r}")


def aggregate(bars: Sequence[DailyBar], interval: str) -> list[Candle]:
    """Candles of ``interval`` from daily ``bars``, in chronological order."""
    ordered = sorted(bars, key=lambda b: b.session_date)
    groups: list[list[DailyBar]] = []
    current: tuple[int, ...] | None = None
    for item in ordered:
        key = bucket(item.session_date, interval)
        if key != current:
            groups.append([])
            current = key
        groups[-1].append(item)
    return [_candle(group) for group in groups]


def _candle(group: list[DailyBar]) -> Candle:
    first, last = group[0], group[-1]
    return Candle(
        session_date=last.session_date,
        period_start=first.session_date,
        open=first.open,
        high=max(b.high for b in group),
        low=min(b.low for b in group),
        close=last.close,
        volume=sum((b.volume for b in group), Decimal(0)),
        adj_close=last.adj_close,
        sessions=len(group),
    )


@dataclass(frozen=True)
class Metrics:
    observations: int
    price_basis: Literal["adjusted_close", "close"]
    period_return: Decimal | None
    annualised_volatility: Decimal | None
    max_drawdown: Decimal | None
    drawdown_peak: date | None
    drawdown_trough: date | None
    unavailable: dict[str, str]  # metric name -> why it has no value


def _step(value: Decimal) -> Decimal:
    return value.quantize(RATIO_STEP)


def compute_metrics(candles: Sequence[Candle], interval: str) -> Metrics:
    """The metrics of a series of candles, on the adjusted close when every candle has one
    (so a split is not a crash), otherwise on the close."""
    adjusted = bool(candles) and all(c.adj_close is not None for c in candles)
    prices = [
        (c.session_date, c.adj_close if adjusted and c.adj_close is not None else c.close)
        for c in candles
    ]
    unavailable: dict[str, str] = {}
    period_return: Decimal | None = None
    volatility: Decimal | None = None
    drawdown: Decimal | None = None
    peak_date: date | None = None
    trough_date: date | None = None

    if len(prices) < 2:
        reason = "needs at least 2 observations"
        unavailable = {
            "period_return": reason,
            "annualised_volatility": reason,
            "max_drawdown": reason,
        }
    else:
        with localcontext() as context:
            context.prec = PRECISION
            first, last = prices[0][1], prices[-1][1]
            if first == 0:
                unavailable["period_return"] = "the first price is zero"
            else:
                period_return = _step(last / first - 1)

            returns: list[Decimal] = []
            for (_, before), (_, after) in pairwise(prices):
                if before <= 0 or after <= 0:
                    returns = []
                    break
                returns.append((after / before).ln())
            if len(returns) < 2:
                unavailable["annualised_volatility"] = "needs at least 3 observations"
            else:
                mean = sum(returns, Decimal(0)) / len(returns)
                variance = sum(((r - mean) ** 2 for r in returns), Decimal(0)) / (len(returns) - 1)
                volatility = _step(variance.sqrt() * Decimal(PERIODS_PER_YEAR[interval]).sqrt())

            peak_price, peak_at = prices[0][1], prices[0][0]
            worst = Decimal(0)
            worst_peak, worst_trough = peak_at, peak_at
            for day, price in prices:
                if price > peak_price:
                    peak_price, peak_at = price, day
                if peak_price != 0:
                    ratio = (price - peak_price) / peak_price
                    if ratio < worst:
                        worst, worst_peak, worst_trough = ratio, peak_at, day
            drawdown = _step(worst)
            if worst < 0:
                peak_date, trough_date = worst_peak, worst_trough

    return Metrics(
        observations=len(prices),
        price_basis="adjusted_close" if adjusted else "close",
        period_return=period_return,
        annualised_volatility=volatility,
        max_drawdown=drawdown,
        drawdown_peak=peak_date,
        drawdown_trough=trough_date,
        unavailable=unavailable,
    )
