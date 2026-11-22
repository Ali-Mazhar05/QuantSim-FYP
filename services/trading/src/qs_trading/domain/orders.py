"""Orders, executed fills and rejections (frozen for tasks A11 to A14).

A strategy returns :class:`OrderIntent` values. The engine validates each one and either
turns it into an :class:`Order` (``ORDER_PLACED``) or a :class:`Rejection`
(``ORDER_REJECTED``). Execution later produces an :class:`Execution` (``ORDER_FILLED``),
whose ``fill`` is the accounting :class:`~qs_trading.domain.accounting.Fill` the books apply,
or the order expires (``ORDER_EXPIRED``).

Rules (ADR 04, lane guide A-FR-05 to A-FR-09): daily bars; a market order placed at session
``t`` fills at the open of ``t + 1`` plus slippage; a limit order rests until the session
range crosses its price, fills at the open when the price gaps through it, and expires after
``expires_after`` sessions. Long only, whole shares.
"""

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from qs_trading.domain.accounting import Fill, Side
from qs_trading.domain.costs import CostBreakdown
from qs_trading.domain.money import price

__all__ = [
    "Execution",
    "Order",
    "OrderIntent",
    "OrderStatus",
    "OrderType",
    "RejectReason",
    "Rejection",
    "Side",
]


class OrderType(StrEnum):
    MARKET = "market"
    LIMIT = "limit"


class OrderStatus(StrEnum):
    OPEN = "open"
    FILLED = "filled"
    REJECTED = "rejected"
    EXPIRED = "expired"


class RejectReason(StrEnum):
    INSUFFICIENT_CASH = "insufficient_cash"
    INSUFFICIENT_POSITION = "insufficient_position"
    MAX_POSITION = "max_position"
    UNKNOWN_SYMBOL = "unknown_symbol"
    NO_PRICE = "no_price"


@dataclass(frozen=True, slots=True)
class OrderIntent:
    """What a strategy asks for. ``limit_price`` is set if and only if the order is a limit;
    ``expires_after`` is the number of sessions a limit may rest (``None`` means until the
    end of the run). Market orders never rest, so they take no expiry."""

    symbol: str
    side: Side
    quantity: int
    order_type: OrderType = OrderType.MARKET
    limit_price: Decimal | None = None
    expires_after: int | None = None

    def __post_init__(self) -> None:
        if not self.symbol:
            raise ValueError("an order needs a symbol")
        if isinstance(self.quantity, bool) or not isinstance(self.quantity, int):
            raise TypeError("quantity must be a whole number of shares")
        if self.quantity <= 0:
            raise ValueError(f"quantity must be above zero, got {self.quantity}")
        object.__setattr__(self, "side", Side(self.side))
        object.__setattr__(self, "order_type", OrderType(self.order_type))
        if self.order_type is OrderType.LIMIT:
            if self.limit_price is None:
                raise ValueError("a limit order needs a limit price")
            object.__setattr__(self, "limit_price", price(self.limit_price))
        else:
            if self.limit_price is not None:
                raise ValueError("a market order takes no limit price")
            if self.expires_after is not None:
                raise ValueError("a market order takes no expiry")
        if self.expires_after is not None and self.expires_after <= 0:
            raise ValueError(f"expires_after must be above zero, got {self.expires_after}")


@dataclass(frozen=True, slots=True)
class Order:
    """An accepted intent. ``placed_session`` is the session the strategy saw;
    ``expires_session`` is the last session a limit may fill in (``None``: never expires)."""

    order_id: str
    intent: OrderIntent
    placed_seq: int
    placed_session: int
    expires_session: int | None = None
    status: OrderStatus = OrderStatus.OPEN


@dataclass(frozen=True, slots=True)
class Execution:
    """A filled order. ``reference_price`` is the price before slippage (the open, or the
    limit price when the range crosses it); ``fill.price`` is after slippage, and
    ``slippage`` is their absolute difference per share. ``fill.cost`` equals
    ``costs.total``."""

    order_id: str
    session: int
    reference_price: Decimal
    slippage: Decimal
    costs: CostBreakdown
    fill: Fill

    def __post_init__(self) -> None:
        if self.fill.cost != self.costs.total:
            raise ValueError("the fill cost must equal the cost breakdown total")


@dataclass(frozen=True, slots=True)
class Rejection:
    """An intent the engine refused; cash and positions are unchanged."""

    intent: OrderIntent
    session: int
    reason: RejectReason
    detail: str = ""
