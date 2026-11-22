"""K6 performance metrics against the exact reference and the error contract (C-FR-05)."""

import json
import math
from collections.abc import Callable
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

import pytest

from qs_quant.metrics import (
    annualised_volatility,
    max_drawdown,
    sharpe,
    simple_returns,
    total_return,
    turnover,
)
from tests import reference as ref

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "metrics_fixture.json").read_text(encoding="utf-8")
)
VALUES = [float(v) for v in FIXTURE["values"]]
EXACT_VALUES = [ref.F(v) for v in FIXTURE["values"]]
FILLS = [float(f) for f in FIXTURE["fills"]]
EXACT_FILLS = [ref.F(f) for f in FIXTURE["fills"]]
RF = ref.F(FIXTURE["rf_annual"])
TOL = 1e-12


def close(got: float | None, expected: float | Fraction) -> bool:
    return got is not None and math.isclose(got, float(expected), rel_tol=TOL)


def test_simple_returns_match_exact() -> None:
    got = simple_returns(VALUES)
    exact = ref.returns(EXACT_VALUES)
    assert len(got) == len(exact) == 24
    assert all(close(float(g), e) for g, e in zip(got, exact, strict=True))


def test_total_return_matches_exact_and_hand_value() -> None:
    assert close(total_return(VALUES), ref.total_return(EXACT_VALUES))
    assert close(total_return(VALUES), Fraction(26, 100))


def test_volatility_matches_exact() -> None:
    rs = simple_returns(VALUES)
    assert close(annualised_volatility(rs), ref.volatility(ref.returns(EXACT_VALUES)))


def test_sharpe_matches_exact_with_and_without_rf() -> None:
    rs = simple_returns(VALUES)
    exact = ref.returns(EXACT_VALUES)
    assert close(sharpe(rs), ref.sharpe(exact))
    assert close(sharpe(rs, rf_annual=float(RF)), ref.sharpe(exact, RF))


def test_max_drawdown_matches_exact_and_hand_value() -> None:
    assert close(max_drawdown(VALUES), ref.max_drawdown(EXACT_VALUES))
    assert close(max_drawdown(VALUES), Fraction(2, 35))


def test_turnover_matches_exact_and_hand_value() -> None:
    assert close(turnover(FILLS, VALUES), ref.turnover(EXACT_FILLS, EXACT_VALUES))
    assert close(turnover(FILLS, VALUES), Fraction(11500) / Fraction(2788, 25))


def test_docstring_examples() -> None:
    assert close(total_return([100, 110, 99, 120]), Fraction(2, 10))
    assert close(max_drawdown([100, 110, 99, 120]), Fraction(1, 10))


def test_undefined_metrics_are_none_or_zero() -> None:
    assert annualised_volatility([0.01]) is None
    assert sharpe([0.01]) is None
    assert sharpe([0.1] * 10) is None  # constant returns: the ptp guard
    assert total_return([100.0]) == 0.0
    assert max_drawdown([]) == 0.0
    assert max_drawdown([1.0, 1.0, 2.0, 3.0, 3.0]) == 0.0
    assert turnover([], [100.0]) == 0.0
    assert simple_returns([100.0]).size == 0


@pytest.mark.parametrize(
    ("call", "message"),
    [
        (lambda: total_return([]), "at least 1"),
        (lambda: total_return([0.0, 1.0]), "V_0 > 0"),
        (lambda: total_return([1.0, float("nan")]), "NaN"),
        (lambda: total_return([[1.0, 2.0]]), "one-dimensional"),
        (lambda: total_return(["a"]), "must be numbers"),
        (lambda: simple_returns([1.0, 0.0, 2.0]), "positive"),
        (lambda: max_drawdown([1.0, -1.0]), "non-negative"),
        (lambda: max_drawdown([0.0, 1.0]), "non-negative"),
        (lambda: turnover([1.0], []), "at least 1"),
        (lambda: turnover([1.0], [0.0, 0.0]), "mean"),
        (lambda: annualised_volatility([0.1, 0.2], periods=0), "periods"),
        (lambda: sharpe([0.1, 0.2], rf_annual=float("inf")), "rf_annual"),
    ],
)
def test_bad_input_raises_value_error(call: Callable[[], object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        call()


def test_decimal_input_is_accepted() -> None:
    assert close(total_return([Decimal("100.00"), Decimal("126.00")]), Fraction(26, 100))


def test_results_are_python_floats() -> None:
    rs = simple_returns(VALUES)
    for result in (
        total_return(VALUES),
        annualised_volatility(rs),
        sharpe(rs),
        max_drawdown(VALUES),
        turnover(FILLS, VALUES),
    ):
        assert type(result) is float
