from decimal import Decimal

import pytest

from qs_trading.domain.money import cents, price


def test_cents_round_half_to_even() -> None:
    assert cents("0.125") == Decimal("0.12")
    assert cents("0.135") == Decimal("0.14")
    assert cents("-0.125") == Decimal("-0.12")
    assert cents(7) == Decimal("7.00")


def test_price_keeps_eight_places_half_to_even() -> None:
    assert price("150.123456785") == Decimal("150.12345678")
    assert price("150.123456775") == Decimal("150.12345678")
    assert price(10) == Decimal("10.00000000")


@pytest.mark.parametrize("bad", [0, "0", "-1", "0.000000004"])
def test_price_must_stay_above_zero(bad: str | int) -> None:
    with pytest.raises(ValueError, match="above zero"):
        price(bad)


@pytest.mark.parametrize("bad", [1.5, True])
def test_float_and_bool_are_refused(bad: object) -> None:
    with pytest.raises(TypeError):
        cents(bad)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        price(bad)  # type: ignore[arg-type]


@pytest.mark.parametrize("bad", ["abc", "NaN", "Infinity", ""])
def test_non_numbers_are_refused(bad: str) -> None:
    with pytest.raises(ValueError):
        cents(bad)
