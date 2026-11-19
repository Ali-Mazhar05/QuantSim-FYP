"""Trade log event types and payloads (frozen for tasks A13 to A15).

Every state change of a portfolio is one row of the append-only ``trade_event`` log:
``(portfolio_id, seq, event_time, type, version, payload, prev_hash, hash)``. ``seq`` starts
at 1 with no gaps; ``hash_n = H(hash_(n-1) || event_n)`` (A-FR-10). The payload is one of
the versioned models below, stored as JSONB. Money travels as decimal strings, never floats
(NFR-INT-001), so a payload reads back to exactly the value that was written.

A payload model only ever gains optional fields; a breaking change adds a ``V2`` model next
to ``V1`` and the rebuild reads both.
"""

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict

from qs_trading.domain.accounting import Side
from qs_trading.domain.orders import OrderType, RejectReason


class EventType(StrEnum):
    RUN_STARTED = "RUN_STARTED"
    TICK = "TICK"
    ORDER_PLACED = "ORDER_PLACED"
    ORDER_REJECTED = "ORDER_REJECTED"
    ORDER_FILLED = "ORDER_FILLED"
    ORDER_EXPIRED = "ORDER_EXPIRED"
    VALUED = "VALUED"
    RUN_COMPLETED = "RUN_COMPLETED"


class Payload(BaseModel):
    """Base of every event payload: immutable, and unknown fields are refused on write."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    type: ClassVar[EventType]
    version: ClassVar[int] = 1


class RunStartedV1(Payload):
    """The run's full spec, so the log alone says what was run on which data."""

    type: ClassVar[EventType] = EventType.RUN_STARTED

    strategy_kind: str
    strategy_params: dict[str, Any]
    initial_capital: Decimal
    cost_model: dict[str, Any]
    slippage_model: dict[str, Any]
    env_type: Literal["replay", "simulation"]
    env_id: str
    path_index: int | None = None
    source_fingerprint: str


class TickV1(Payload):
    """The engine consumed every tick of one session (source ``seq`` range inclusive)."""

    type: ClassVar[EventType] = EventType.TICK

    session: int
    ts: datetime
    first_tick_seq: int
    last_tick_seq: int


class OrderPlacedV1(Payload):
    type: ClassVar[EventType] = EventType.ORDER_PLACED

    order_id: str
    session: int
    symbol: str
    side: Side
    quantity: int
    order_type: OrderType
    limit_price: Decimal | None = None
    expires_session: int | None = None


class OrderRejectedV1(Payload):
    """An intent refused at placement (``order_id`` is ``None``), or a placed order refused
    when it came to fill (``order_id`` names its ``ORDER_PLACED``)."""

    type: ClassVar[EventType] = EventType.ORDER_REJECTED

    session: int
    symbol: str
    side: Side
    quantity: int
    order_type: OrderType
    limit_price: Decimal | None = None
    reason: RejectReason
    detail: str = ""
    order_id: str | None = None


class OrderFilledV1(Payload):
    type: ClassVar[EventType] = EventType.ORDER_FILLED

    order_id: str
    session: int
    symbol: str
    side: Side
    quantity: int
    reference_price: Decimal
    fill_price: Decimal
    slippage: Decimal
    cost_fixed: Decimal
    cost_per_share: Decimal
    cost_percentage: Decimal
    cost_total: Decimal
    cash_after: Decimal


class OrderExpiredV1(Payload):
    type: ClassVar[EventType] = EventType.ORDER_EXPIRED

    order_id: str
    session: int


class ValuedV1(Payload):
    """The portfolio valued at the session close."""

    type: ClassVar[EventType] = EventType.VALUED

    session: int
    ts: datetime
    cash: Decimal
    market_value: Decimal
    portfolio_value: Decimal
    realised_pnl: Decimal
    unrealised_pnl: Decimal
    total_costs: Decimal


class RunCompletedV1(Payload):
    type: ClassVar[EventType] = EventType.RUN_COMPLETED

    sessions: int
    final_value: Decimal


PAYLOADS: dict[tuple[EventType, int], type[Payload]] = {
    (model.type, model.version): model
    for model in (
        RunStartedV1,
        TickV1,
        OrderPlacedV1,
        OrderRejectedV1,
        OrderFilledV1,
        OrderExpiredV1,
        ValuedV1,
        RunCompletedV1,
    )
}
"""Every payload model, by ``(type, version)``: what the rebuild uses to read a row."""
