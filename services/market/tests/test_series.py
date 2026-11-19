"""Interval aggregation and metrics (FYP TC-MKT-02 and TC-MET-01).

The expected values are worked out by hand in the comments, or by numpy as an independent
implementation, not by the code under test."""

import math
from datetime import date, timedelta
from decimal import Decimal

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from qs_market.series import Candle, DailyBar, aggregate, compute_metrics

D = Decimal


def bar(day: str, o: str, h: str, low: str, c: str, v: str, adj: str | None = None) -> DailyBar:
    return DailyBar(
        date.fromisoformat(day), D(o), D(h), D(low), D(c), D(v), None if adj is None else D(adj)
    )


# Two January weeks. Week 1 holds Tue 2 to Fri 5 (Thursday is missing on purpose), week 2
# holds Mon 8 and Tue 9.
JANUARY = [
    bar("2024-01-02", "10", "12", "9", "11", "100"),
    bar("2024-01-03", "11", "13", "10", "12", "200"),
    bar("2024-01-05", "12", "14", "11", "13", "300"),
    bar("2024-01-08", "13", "15", "12", "14", "400"),
    bar("2024-01-09", "14", "16", "8", "9", "500"),
]


def test_daily_is_the_stored_series_unchanged() -> None:
    candles = aggregate(JANUARY, "daily")
    assert [c.session_date for c in candles] == [b.session_date for b in JANUARY]
    assert [(c.open, c.high, c.low, c.close, c.volume) for c in candles] == [
        (b.open, b.high, b.low, b.close, b.volume) for b in JANUARY
    ]
    assert all(c.sessions == 1 for c in candles)


def test_weekly_buckets_follow_first_max_min_last_sum() -> None:
    week1, week2 = aggregate(JANUARY, "weekly")
    # week 1: open of Jan 2 = 10, highest high 14, lowest low 9, close of Jan 5 = 13,
    # volume 100 + 200 + 300 = 600
    assert (week1.open, week1.high, week1.low, week1.close, week1.volume) == (
        D(10),
        D(14),
        D(9),
        D(13),
        D(600),
    )
    assert (week1.period_start, week1.session_date, week1.sessions) == (
        date(2024, 1, 2),
        date(2024, 1, 5),
        3,
    )
    # week 2: open of Jan 8 = 13, high 16, low 8, close of Jan 9 = 9, volume 900
    assert (week2.open, week2.high, week2.low, week2.close, week2.volume) == (
        D(13),
        D(16),
        D(8),
        D(9),
        D(900),
    )
    assert (week2.period_start, week2.session_date) == (date(2024, 1, 8), date(2024, 1, 9))


def test_monthly_and_yearly_hold_the_whole_window() -> None:
    (month,) = aggregate(JANUARY, "monthly")
    (year,) = aggregate(JANUARY, "yearly")
    for candle in (month, year):
        assert (candle.open, candle.high, candle.low, candle.close, candle.volume) == (
            D(10),
            D(16),
            D(8),
            D(9),
            D(1500),
        )
        assert candle.sessions == 5


def test_year_end_week_belongs_to_one_iso_week_but_two_calendar_years() -> None:
    bars = [
        bar("2024-12-27", "1", "2", "1", "2", "10"),  # Fri, ISO 2024-W52
        bar("2024-12-30", "2", "3", "2", "3", "10"),  # Mon, ISO 2025-W01
        bar("2024-12-31", "3", "4", "3", "4", "10"),  # Tue, ISO 2025-W01
        bar("2025-01-02", "4", "5", "4", "5", "10"),  # Thu, ISO 2025-W01
    ]
    weekly = aggregate(bars, "weekly")
    assert [c.sessions for c in weekly] == [1, 3]  # Dec 30 to Jan 2 is one ISO week
    monthly = aggregate(bars, "monthly")
    assert [c.sessions for c in monthly] == [3, 1]  # December, January
    yearly = aggregate(bars, "yearly")
    assert [(c.sessions, c.close) for c in yearly] == [(3, D(4)), (1, D(5))]


def test_input_order_does_not_matter_and_empty_is_empty() -> None:
    assert aggregate(list(reversed(JANUARY)), "weekly") == aggregate(JANUARY, "weekly")
    assert aggregate([], "monthly") == []


def test_unknown_interval_is_refused() -> None:
    with pytest.raises(ValueError):
        aggregate(JANUARY, "hourly")


def test_adjusted_close_of_a_bucket_is_the_last_sessions() -> None:
    bars = [
        bar("2024-01-02", "10", "12", "9", "11", "100", adj="5.5"),
        bar("2024-01-03", "11", "13", "10", "12", "200", adj="6"),
    ]
    (week,) = aggregate(bars, "weekly")
    assert week.adj_close == D(6)


def closes(*values: str) -> list[Candle]:
    start = date(2024, 1, 1)
    return [
        Candle(
            start + timedelta(days=i),
            start + timedelta(days=i),
            D(v),
            D(v),
            D(v),
            D(v),
            D(1),
            None,
            1,
        )
        for i, v in enumerate(values)
    ]


def test_metrics_match_a_hand_computed_series() -> None:
    metrics = compute_metrics(closes("100", "110", "99", "120"), "daily")
    # period return: 120 / 100 - 1 = 0.2
    assert metrics.period_return == D("0.2")
    # peak 110 then 99: (99 - 110) / 110 = -0.1 is the lowest ratio (120 is a new peak)
    assert metrics.max_drawdown == D("-0.1")
    assert (metrics.drawdown_peak, metrics.drawdown_trough) == (date(2024, 1, 2), date(2024, 1, 3))
    assert metrics.observations == 4
    assert metrics.price_basis == "close"
    # volatility by numpy: sample std of the log returns times sqrt(252)
    expected = float(np.std(np.diff(np.log([100, 110, 99, 120])), ddof=1) * math.sqrt(252))
    assert metrics.annualised_volatility is not None
    assert abs(float(metrics.annualised_volatility) - expected) < 1e-9
    assert metrics.unavailable == {}


def test_volatility_is_annualised_by_the_interval() -> None:
    series = closes("100", "104", "101", "108", "103")
    log_returns = np.diff(np.log([100, 104, 101, 108, 103]))
    for interval, periods in (("daily", 252), ("weekly", 52), ("monthly", 12)):
        value = compute_metrics(series, interval).annualised_volatility
        assert value is not None
        assert abs(float(value) - float(np.std(log_returns, ddof=1) * math.sqrt(periods))) < 1e-9


def test_a_rising_series_has_no_drawdown() -> None:
    metrics = compute_metrics(closes("1", "2", "3"), "daily")
    assert metrics.max_drawdown == D(0)
    assert metrics.drawdown_peak is None and metrics.drawdown_trough is None


def test_too_few_observations_give_no_number_and_a_reason() -> None:
    empty = compute_metrics([], "daily")
    assert empty.observations == 0
    assert (empty.period_return, empty.annualised_volatility, empty.max_drawdown) == (
        None,
        None,
        None,
    )
    assert set(empty.unavailable) == {"period_return", "annualised_volatility", "max_drawdown"}

    single = compute_metrics(closes("5"), "daily")
    assert single.period_return is None and single.max_drawdown is None

    two = compute_metrics(closes("100", "110"), "daily")
    assert two.period_return == D("0.1")
    assert two.max_drawdown == D(0)
    assert two.annualised_volatility is None  # one return has no sample deviation
    assert "annualised_volatility" in two.unavailable


def test_a_zero_first_price_is_refused_explicitly() -> None:
    metrics = compute_metrics(closes("0", "10", "11"), "daily")
    assert metrics.period_return is None
    assert metrics.unavailable["period_return"] == "the first price is zero"
    assert metrics.annualised_volatility is None  # a zero price has no log return


def test_a_split_is_not_a_crash_on_the_adjusted_basis() -> None:
    start = date(2024, 6, 3)
    candles = [
        Candle(start, start, D(1000), D(1000), D(1000), D(1000), D(1), D(100), 1),
        Candle(start + timedelta(days=1), start, D(100), D(100), D(100), D(100), D(1), D(100), 1),
    ]
    metrics = compute_metrics(candles, "daily")
    assert metrics.price_basis == "adjusted_close"
    assert metrics.period_return == D(0)
    assert metrics.max_drawdown == D(0)


sessions = st.lists(
    st.tuples(
        st.integers(0, 1500),
        st.integers(1, 1000),
        st.integers(1, 1000),
        st.integers(0, 10**6),
    ),
    min_size=1,
    max_size=120,
    unique_by=lambda t: t[0],
)


@given(sessions, st.sampled_from(["daily", "weekly", "monthly", "yearly"]))
def test_aggregation_never_loses_a_session_or_a_share(
    rows: list[tuple[int, int, int, int]], interval: str
) -> None:
    start = date(2015, 1, 2)
    bars = []
    for offset, a, b, volume in rows:
        low, high = min(a, b), max(a, b)
        bars.append(
            DailyBar(start + timedelta(days=offset), D(low), D(high), D(low), D(high), D(volume))
        )
    candles = aggregate(bars, interval)
    assert sum(c.sessions for c in candles) == len(bars)
    assert sum((c.volume for c in candles), D(0)) == sum((b.volume for b in bars), D(0))
    assert [c.session_date for c in candles] == sorted({c.session_date for c in candles})
    assert all(c.low <= c.high for c in candles)
    assert max(c.high for c in candles) == max(b.high for b in bars)
    assert min(c.low for c in candles) == min(b.low for b in bars)
