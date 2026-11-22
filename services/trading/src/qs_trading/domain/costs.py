"""Transaction cost model interface (frozen for task A11, which adds the implementation).

Every fill pays ``fixed + per_share * quantity + pct * notional`` (A-FR-08). Each part is
rounded to cents, half to even, and ``total`` is their sum, so the breakdown shown on Trade
Replay always adds up to what the books charged.

:class:`LinearCostModel` is the implementation (A11). It is a Pydantic model so that it is
stored as the portfolio's ``cost_model`` JSON (``{"fixed": "1.00", "per_share": "0.005",
"pct": "0.0005"}``, money as decimal strings) and rebuilt from it with
:func:`cost_model_from_json`. ``pct`` is a fraction of the notional, not a percentage
(``"0.0005"`` is 5 basis points). The percentage part is charged on the notional the books
use, ``cents(quantity * fill_price)``.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Annotated, Any, Protocol

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

from qs_trading.domain.money import cents, to_decimal

ZERO = Decimal("0.00")


@dataclass(frozen=True, slots=True)
class CostBreakdown:
    """The cost of one fill, by component, in cents."""

    fixed: Decimal = ZERO
    per_share: Decimal = ZERO
    percentage: Decimal = ZERO

    def __post_init__(self) -> None:
        for name in ("fixed", "per_share", "percentage"):
            value = cents(getattr(self, name))
            if value < 0:
                raise ValueError(f"{name} cost cannot be negative, got {value}")
            object.__setattr__(self, name, value)

    @property
    def total(self) -> Decimal:
        return self.fixed + self.per_share + self.percentage


class CostModel(Protocol):
    """Prices the cost of filling ``quantity`` shares at ``fill_price``."""

    def cost(self, quantity: int, fill_price: Decimal) -> CostBreakdown: ...


def _exact_decimal(value: Any) -> Decimal:
    """Pydantic hook: a finite ``Decimal`` from a Decimal, int or str; floats are refused."""
    try:
        return to_decimal(value)
    except TypeError as exc:
        raise ValueError(str(exc)) from exc


ExactDecimal = Annotated[Decimal, BeforeValidator(_exact_decimal)]
"""A model parameter read as an exact ``Decimal`` (a JSON float is refused, NFR-INT-001)."""

NonNegative = Annotated[ExactDecimal, Field(ge=0)]


class LinearCostModel(BaseModel):
    """``fixed + per_share * quantity + pct * notional`` per fill (A-FR-08). Every
    parameter defaults to zero, so ``{}`` is a free broker."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    fixed: NonNegative = Decimal("0")
    per_share: NonNegative = Decimal("0")
    pct: NonNegative = Decimal("0")

    def cost(self, quantity: int, fill_price: Decimal) -> CostBreakdown:
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
            raise ValueError(f"quantity must be a whole number above zero, got {quantity!r}")
        notional = cents(quantity * fill_price)
        return CostBreakdown(
            fixed=self.fixed,
            per_share=self.per_share * quantity,
            percentage=self.pct * notional,
        )

    def to_json(self) -> dict[str, Any]:
        """The stored form: every parameter as a decimal string."""
        return self.model_dump(mode="json")


def cost_model_from_json(data: Mapping[str, Any]) -> LinearCostModel:
    """Rebuild a cost model from the portfolio's stored ``cost_model`` JSON. Raises a
    Pydantic ``ValidationError`` naming the field for unknown keys, floats or negatives."""
    return LinearCostModel.model_validate(dict(data))
