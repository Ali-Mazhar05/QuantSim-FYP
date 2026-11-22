"""Run metrics from the shared metrics library (A16, A-FR-14): hand-computed series, the
conversion to stored ratios, and the cases where a ratio is undefined."""

import uuid
from decimal import Decimal as D

from qs_trading.metrics import (
    PENDING,
    QUANT_METRICS,
    RATIO_PLACES,
    RunFigures,
    SeriesMetrics,
    to_ratio,
)


def figures(*values: str, notional: str = "0") -> RunFigures:
    return RunFigures(
        portfolio_id=uuid.uuid4(),
        initial_capital=D("10000.00"),
        values=tuple(D(v) for v in values),
        trades=1 if notional != "0" else 0,
        total_costs=D("0"),
        traded_notional=D(notional),
        final_seq=len(values) * 3,
        final_hash="h",
    )


def ratio_text(x: float) -> str:
    """The stored ratio as text, so the scale is checked too (Decimal == ignores it)."""
    value = to_ratio(x)
    assert value is not None
    return format(value, "f")


def test_to_ratio_rounds_half_even_to_twelve_places() -> None:
    assert to_ratio(None) is None
    assert ratio_text(0.1) == "0.100000000000"
    assert ratio_text(2.5e-12) == "0.000000000002"  # half-even: 2.5 -> 2
    assert ratio_text(3.5e-12) == "0.000000000004"  # half-even: 3.5 -> 4
    assert ratio_text(-0.25) == "-0.250000000000"
    assert RATIO_PLACES == D("1e-12")


def test_to_ratio_leaves_out_what_the_column_cannot_hold() -> None:
    assert to_ratio(1e9) is None
    assert to_ratio(-1e9) is None
    assert to_ratio(99_999_999.0) == D("99999999.000000000000")


def test_hand_computed_series_starts_from_the_money_put_in() -> None:
    # Series 10000 -> 10500 -> 9975 -> 11000: total return 11000/10000 - 1, drawdown
    # 1 - 9975/10500 (peak 10500), turnover 5000 / mean(10000, 10500, 9975, 11000)
    got = QUANT_METRICS.series_metrics(figures("10500.00", "9975.00", "11000.00", notional="5000"))
    assert got.total_return == D("0.100000000000")
    assert got.max_drawdown == D("0.050000000000")
    assert got.turnover is not None
    assert abs(got.turnover - D(5000) / D("10368.75")) < D("1e-12")
    assert got.volatility is not None and got.volatility > 0
    assert got.sharpe is not None
    assert got.pending() == []


def test_the_first_session_counts() -> None:
    # One valued session below the capital: a loss of 1% and a 1% drawdown, which a
    # series starting at the first session would not show
    got = QUANT_METRICS.series_metrics(figures("9900.00"))
    assert got.total_return == D("-0.010000000000")
    assert got.max_drawdown == D("0.010000000000")


def test_one_session_leaves_volatility_and_sharpe_undefined() -> None:
    got = QUANT_METRICS.series_metrics(figures("10100.00"))
    assert got.total_return == D("0.010000000000")
    assert got.pending() == ["volatility", "sharpe"]


def test_no_valued_session_computes_nothing() -> None:
    assert QUANT_METRICS.series_metrics(figures()) == SeriesMetrics()


def test_a_value_of_zero_keeps_return_and_drawdown() -> None:
    got = QUANT_METRICS.series_metrics(figures("5000.00", "0.00"))
    assert got.total_return == D("-1.000000000000")
    assert got.max_drawdown == D("1.000000000000")
    assert got.volatility is None
    assert got.sharpe is None


def test_constant_value_has_no_sharpe() -> None:
    got = QUANT_METRICS.series_metrics(figures("10000.00", "10000.00", "10000.00"))
    assert got.total_return == D("0.000000000000")
    assert got.volatility == D("0.000000000000")
    assert got.sharpe is None


def test_pending_computes_nothing() -> None:
    assert PENDING.series_metrics(figures("10500.00")) == SeriesMetrics()


def test_the_library_version_is_recorded() -> None:
    import qs_quant

    assert QUANT_METRICS.version == qs_quant.__version__
