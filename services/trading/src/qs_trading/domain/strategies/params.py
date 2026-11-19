"""Typed strategy parameters (task A12, A-FR-01; ADR 05: ``kind`` plus ``params`` JSONB).

Each built-in kind has one Pydantic model. Models are strict and refuse unknown fields, so a
typo or an out-of-range value raises a ``ValidationError`` whose ``loc`` names the field;
the API turns that into a 422 naming the field.

Parameters are stored as JSONB, so every model round-trips through JSON:
``Model.model_validate(params.model_dump(mode="json")) == params``. Fractions are
``Decimal`` and dump as decimal strings. On input a fraction may be a ``Decimal``, an
``int``, a decimal string or a JSON number; a float is read through its shortest ``repr``
(``0.1`` becomes ``Decimal("0.1")``), so the value a client typed is the value stored.
Booleans and non-finite numbers are refused.
"""

from decimal import Decimal, InvalidOperation
from typing import Annotated, ClassVar

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

__all__ = ["DEFAULT_CASH_BUFFER", "Fraction", "StrategyParams"]

DEFAULT_CASH_BUFFER = Decimal("0.02")


def _to_fraction(value: object) -> object:
    if isinstance(value, bool):
        raise ValueError("must be a number, not a boolean")
    if isinstance(value, float):
        value = repr(value)
    if isinstance(value, int | str):
        try:
            value = Decimal(value)
        except InvalidOperation:
            raise ValueError(f"not a number: {value!r}") from None
    if isinstance(value, Decimal) and not value.is_finite():
        raise ValueError("must be a finite number")
    return value


Fraction = Annotated[Decimal, BeforeValidator(_to_fraction)]
"""A decimal read from JSON without binary rounding (see the module docstring)."""


class StrategyParams(BaseModel):
    """Base of every parameter model: strict, immutable, unknown fields refused.

    ``cash_buffer`` is the fraction of portfolio value a strategy keeps in cash when it
    sizes buys. It pays costs and slippage, and absorbs the move from the close the order
    was sized at to the next open it fills at."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    kind: ClassVar[str]

    cash_buffer: Annotated[Fraction, Field(ge=0, lt=Decimal("0.5"))] = DEFAULT_CASH_BUFFER
