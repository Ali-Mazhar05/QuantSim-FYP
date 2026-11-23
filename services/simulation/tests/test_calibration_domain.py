"""Calibration inputs: the fingerprint, the window checks and the arrays a fit reads (B15)."""

import math
from datetime import date
from decimal import Decimal

import numpy as np
import pytest

from qs_simulation.domain.calibration import (
    INSUFFICIENT_HISTORY,
    INVALID_PRICES,
    MIN_SESSIONS,
    CalibrationRefused,
    PricePoint,
    check_window,
    input_fingerprint,
    log_prices,
    log_returns,
    ordered,
)
from tests.calibration_support import make_points


def point(day: str, close: str, revision: int = 1) -> PricePoint:
    return PricePoint(date.fromisoformat(day), Decimal(close), revision)


# ---- the fingerprint ----


def test_the_fingerprint_names_its_algorithm_and_is_stable() -> None:
    points = make_points(80)
    value = input_fingerprint(points)
    assert value.startswith("xxh3:") and len(value) == len("xxh3:") + 32
    assert input_fingerprint(make_points(80)) == value


def test_the_fingerprint_does_not_depend_on_the_order_or_the_scale_of_the_closes() -> None:
    a = [point("2024-01-02", "100"), point("2024-01-03", "101.5")]
    b = [point("2024-01-03", "101.5000000000"), point("2024-01-02", "100.0000000000")]
    assert input_fingerprint(a) == input_fingerprint(b)


def test_the_fingerprint_changes_when_a_close_is_restated() -> None:
    points = make_points(80)
    restated = [*points[:10], PricePoint(points[10].session_date, points[10].adj_close * 2, 1)]
    restated += points[11:]
    assert input_fingerprint(restated) != input_fingerprint(points)


def test_the_fingerprint_changes_when_a_revision_lands_with_the_same_close() -> None:
    points = make_points(80)
    revised = [*points[:5], PricePoint(points[5].session_date, points[5].adj_close, 2), *points[6:]]
    assert input_fingerprint(revised) != input_fingerprint(points)


def test_the_fingerprint_changes_when_a_session_is_added_or_removed() -> None:
    points = make_points(80)
    assert input_fingerprint(points[:-1]) != input_fingerprint(points)
    assert input_fingerprint(points[1:]) != input_fingerprint(points)


def test_a_tiny_change_below_the_stored_scale_does_not_change_the_fingerprint() -> None:
    a = [point("2024-01-02", "100.00000000001")]
    b = [point("2024-01-02", "100.00000000002")]
    assert input_fingerprint(a) == input_fingerprint(b)  # closes are kept to 10 decimals


# ---- the window checks ----


def test_fewer_than_sixty_sessions_are_refused_with_the_count() -> None:
    with pytest.raises(CalibrationRefused) as refused:
        check_window(make_points(MIN_SESSIONS - 1))
    assert refused.value.code == INSUFFICIENT_HISTORY
    assert "59 sessions" in refused.value.reason and "60" in refused.value.reason


def test_sixty_sessions_pass_and_come_back_in_order() -> None:
    points = make_points(MIN_SESSIONS)
    shuffled = points[::-1]
    assert check_window(shuffled) == points


def test_a_session_twice_is_refused() -> None:
    points = make_points(70)
    with pytest.raises(CalibrationRefused) as refused:
        ordered([*points, points[3]])
    assert refused.value.code == INVALID_PRICES and points[3].session_date.isoformat() in str(
        refused.value
    )


@pytest.mark.parametrize("bad", ["0", "-1.5", "NaN", "Infinity"])
def test_a_close_without_a_logarithm_is_refused_before_any_model_is_asked(bad: str) -> None:
    points = make_points(70)
    spoiled = [*points[:30], PricePoint(points[30].session_date, Decimal(bad), 1), *points[31:]]
    with pytest.raises(CalibrationRefused) as refused:
        check_window(spoiled)
    assert refused.value.code == INVALID_PRICES
    assert points[30].session_date.isoformat() in refused.value.reason


# ---- what a fit reads ----


def test_log_prices_and_returns_follow_the_sessions_in_order() -> None:
    points = [point("2024-01-03", "110"), point("2024-01-02", "100"), point("2024-01-04", "99")]
    assert log_prices(points) == pytest.approx([math.log(100), math.log(110), math.log(99)])
    returns = log_returns(points)
    assert returns.shape == (2,)
    assert returns == pytest.approx([math.log(1.1), math.log(0.9)])
    assert returns.sum() == pytest.approx(np.log(99 / 100))
