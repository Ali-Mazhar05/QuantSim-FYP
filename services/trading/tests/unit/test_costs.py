"""Hand-computed fixtures for the transaction cost model (A-FR-08)."""

from decimal import Decimal as D

import pytest
from pydantic import ValidationError

from qs_trading.domain.costs import CostBreakdown, LinearCostModel, cost_model_from_json


def model(fixed: str = "0", per_share: str = "0", pct: str = "0") -> LinearCostModel:
    return LinearCostModel(fixed=D(fixed), per_share=D(per_share), pct=D(pct))


def test_fixed_component_only() -> None:
    assert model(fixed="1.00").cost(10, D("100.05")) == CostBreakdown(fixed=D("1.00"))


def test_per_share_component_only() -> None:
    # 0.005 * 10 = 0.05
    assert model(per_share="0.005").cost(10, D("100.05")) == CostBreakdown(per_share=D("0.05"))


def test_percentage_component_is_charged_on_the_rounded_notional() -> None:
    # notional = cents(10 * 100.05) = 1000.50; 0.0005 * 1000.50 = 0.50025 -> 0.50
    assert model(pct="0.0005").cost(10, D("100.05")) == CostBreakdown(percentage=D("0.50"))


def test_all_components_and_their_sum() -> None:
    costs = model("1.00", "0.005", "0.0005").cost(10, D("100.05"))
    assert (costs.fixed, costs.per_share, costs.percentage) == (D("1.00"), D("0.05"), D("0.50"))
    assert costs.total == D("1.55")


def test_each_part_rounds_half_to_even() -> None:
    # fixed: 0.125 -> 0.12 (a tie, to even); per share: 0.0025 * 7 = 0.0175 -> 0.02
    # pct: 0.001 * cents(7 * 1.25) = 0.001 * 8.75 = 0.00875 -> 0.01
    costs = model("0.125", "0.0025", "0.001").cost(7, D("1.25"))
    assert (costs.fixed, costs.per_share, costs.percentage) == (D("0.12"), D("0.02"), D("0.01"))
    assert costs.total == D("0.15")


def test_an_empty_config_is_free() -> None:
    assert cost_model_from_json({}).cost(100, D("50")).total == D("0.00")


def test_round_trips_through_the_stored_json() -> None:
    original = model("1.00", "0.005", "0.0005")
    stored = original.to_json()
    assert stored == {"fixed": "1.00", "per_share": "0.005", "pct": "0.0005"}
    assert cost_model_from_json(stored) == original


@pytest.mark.parametrize(
    "data",
    [
        {"fixed": "-1"},
        {"per_share": 0.01},
        {"pct": True},
        {"pct": "abc"},
        {"pct": "NaN"},
        {"commission": "1"},
    ],
)
def test_refuses_invalid_config(data: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        cost_model_from_json(data)


@pytest.mark.parametrize("quantity", [0, -1, True])
def test_refuses_a_bad_quantity(quantity: int) -> None:
    with pytest.raises(ValueError):
        model(fixed="1").cost(quantity, D("10"))


def test_is_immutable() -> None:
    costs = model(fixed="1")
    with pytest.raises(ValidationError):
        costs.fixed = D("2")  # type: ignore[misc]
