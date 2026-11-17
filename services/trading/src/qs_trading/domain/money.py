"""Money and price arithmetic.

Cash is held in whole cents and prices to 8 decimal places, both as ``Decimal`` rounded
half to even (NFR-INT-001). A ``float`` is refused everywhere, so binary rounding never
reaches the books.
"""

from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation

CENT = Decimal("0.01")
PRICE_STEP = Decimal("0.00000001")

Amount = Decimal | int | str


def to_decimal(value: Amount) -> Decimal:
    """Convert to a finite ``Decimal``; floats and bools are refused."""
    if isinstance(value, bool | float):
        raise TypeError(f"money must be a Decimal, int or str, not {type(value).__name__}")
    try:
        result = Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"not a number: {value!r}") from exc
    if not result.is_finite():
        raise ValueError(f"not a finite number: {value!r}")
    return result


def cents(value: Amount) -> Decimal:
    """Round an amount to whole cents, half to even."""
    return to_decimal(value).quantize(CENT, rounding=ROUND_HALF_EVEN)


def price(value: Amount) -> Decimal:
    """Round a price to 8 decimal places, half to even; it must stay above zero."""
    result = to_decimal(value).quantize(PRICE_STEP, rounding=ROUND_HALF_EVEN)
    if result <= 0:
        raise ValueError(f"a price must be above zero, got {value!r}")
    return result
