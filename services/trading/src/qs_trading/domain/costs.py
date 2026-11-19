"""Transaction cost model interface (frozen for task A11, which adds the implementation).

Every fill pays ``fixed + per_share * quantity + pct * notional`` (A-FR-08). Each part is
rounded to cents, half to even, and ``total`` is their sum, so the breakdown shown on Trade
Replay always adds up to what the books charged.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from qs_trading.domain.money import cents

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
