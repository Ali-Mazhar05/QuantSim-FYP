"""Returns and volatility (PRD FR-27; SPEC FR-MKT-003) against hand-computed values."""

import math
import statistics
from datetime import date, timedelta
from decimal import Decimal

import pytest

from qs_market.returns import PricePoint, compute

TOLERANCE = 1e-8


def series(closes: list[str], adjusted: list[str] | None = None) -> list[PricePoint]:
    start = date(2025, 1, 2)
    return [
        PricePoint(
            session_date=start + timedelta(days=i),
            close=Decimal(c),
            adj_close=Decimal(adjusted[i]) if adjusted else None,
        )
        for i, c in enumerate(closes)
    ]


def test_log_returns_match_hand_computed_values() -> None:
    result = compute(series(["100", "110", "99"]))
    assert result[0].log_return is None
    assert result[1].log_return == pytest.approx(math.log(110 / 100), abs=TOLERANCE)
    assert result[2].log_return == pytest.approx(math.log(99 / 110), abs=TOLERANCE)


def test_volatility_is_the_annualised_sample_deviation_of_adjusted_returns() -> None:
    closes = [str(100 + (i % 7) - 3 + i * 0.1) for i in range(61)]
    result = compute(series(closes))
    returns = [math.log(float(closes[i]) / float(closes[i - 1])) for i in range(1, 61)]
    assert result[19].vol_20d is None  # only 19 returns exist on the 20th session
    assert result[20].vol_20d == pytest.approx(
        statistics.stdev(returns[:20]) * math.sqrt(252), abs=TOLERANCE
    )
    assert result[59].vol_60d is None
    assert result[60].vol_60d == pytest.approx(
        statistics.stdev(returns[:60]) * math.sqrt(252), abs=TOLERANCE
    )
    assert result[60].vol_20d == pytest.approx(
        statistics.stdev(returns[40:60]) * math.sqrt(252), abs=TOLERANCE
    )


def test_a_split_day_shows_no_jump_in_the_adjusted_return() -> None:
    # 2-for-1 split on the third session: the raw close halves, the adjusted one does not
    result = compute(series(["200", "202", "101"], adjusted=["100", "101", "101"]))
    assert result[2].log_return == pytest.approx(math.log(101 / 202), abs=TOLERANCE)
    assert result[2].adj_log_return == pytest.approx(0.0, abs=TOLERANCE)


def test_a_dividend_day_uses_the_adjusted_closes() -> None:
    result = compute(series(["50", "49.5"], adjusted=["49.75", "49.5"]))
    assert result[1].adj_log_return == pytest.approx(math.log(49.5 / 49.75), abs=TOLERANCE)
