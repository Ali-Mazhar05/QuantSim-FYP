"""Order execution on daily bars (task A11, ADR 04).

Pure functions the engine (A14) calls once per session; no I/O, no clock.

Placement (A-FR-07). :func:`validate_intent` checks an intent against the portfolio before it
becomes an order. A buy must be payable, costs included, at an estimate of its fill: a market
buy at the latest price (the close the strategy saw) plus slippage, a limit buy at its limit
price, which is the worst it can ever fill at. A sale may not exceed the shares held. A
refused intent gives a :class:`~qs_trading.domain.orders.Rejection` and changes nothing. The
engine passes the cash and shares already committed to earlier orders of the same session as
``reserved_cash`` and ``reserved_shares``; :func:`required_cash` gives each order's share.

Fills (A-FR-05, A-FR-06). An order never fills on the session it was placed in, because the
strategy saw that session's close. From the next session:

* a market order fills at the open, moved against the trader by the slippage model; a market
  order whose fill session has no bar for its symbol is rejected with ``NO_PRICE``;
* a buy limit fills at the open when the session opens at or below the limit (a gap through
  it), else at the limit when the low reaches it; a sell limit mirrors this with the high;
* slippage applies to a limit fill too, but a limit fill is never worse than its limit price:
  a buy is capped at the limit and a sale floored at it;
* costs come from the cost model on the slipped price (A-FR-08, A-FR-09).

Because the open may move between placement and fill, a fill is checked against the books
again; one the portfolio cannot pay for (or a sale of shares no longer held) is rejected with
cash and positions unchanged, so :func:`~qs_trading.domain.accounting.apply_fill` never
refuses an :class:`~qs_trading.domain.orders.Execution` this module returns.

Expiry (A-FR-06). ``expires_session`` is the last session a limit may fill in. A limit still
unfilled at the end of that session gives an :class:`Expiry` in the same session, so the
engine logs ``ORDER_EXPIRED`` even when it is the last session of the run; an order the engine
offers after its last session expires straight away.
"""

from dataclasses import dataclass
from decimal import Decimal

from qs_trading.domain.accounting import (
    ZERO,
    AccountingError,
    Fill,
    InsufficientPosition,
    PortfolioState,
    Side,
    apply_fill,
)
from qs_trading.domain.costs import CostModel
from qs_trading.domain.money import price
from qs_trading.domain.orders import (
    Execution,
    Order,
    OrderIntent,
    OrderStatus,
    OrderType,
    Rejection,
    RejectReason,
)
from qs_trading.domain.slippage import SlippageModel
from qs_trading.domain.strategy import Bar

__all__ = [
    "Expiry",
    "Outcome",
    "expiry_session",
    "limit_reference",
    "place_order",
    "process_order",
    "required_cash",
    "validate_intent",
]


@dataclass(frozen=True, slots=True)
class Expiry:
    """A limit order that reached the end of its life unfilled (``ORDER_EXPIRED``)."""

    order_id: str
    session: int


Outcome = Execution | Rejection | Expiry | None
"""What one session does to an open order; ``None`` means it keeps resting."""


def expiry_session(intent: OrderIntent, placed_session: int) -> int | None:
    """The last session the order may fill in: ``placed_session + expires_after`` for a
    limit with an expiry, ``None`` otherwise (a market order fills or fails next session)."""
    if intent.order_type is OrderType.LIMIT and intent.expires_after is not None:
        return placed_session + intent.expires_after
    return None


def place_order(intent: OrderIntent, *, order_id: str, seq: int, session: int) -> Order:
    """The open order for an intent that passed :func:`validate_intent`."""
    return Order(
        order_id=order_id,
        intent=intent,
        placed_seq=seq,
        placed_session=session,
        expires_session=expiry_session(intent, session),
    )


def _estimated_price(
    intent: OrderIntent, last_price: Decimal, bar_volume: Decimal, slippage: SlippageModel
) -> Decimal:
    if intent.limit_price is not None and intent.side is Side.BUY:
        return intent.limit_price
    return slippage.fill_price(intent.side, intent.quantity, price(last_price), bar_volume)


def required_cash(
    intent: OrderIntent,
    *,
    last_price: Decimal,
    bar_volume: Decimal,
    costs: CostModel,
    slippage: SlippageModel,
) -> Decimal:
    """The cash a buy is expected to need, notional plus costs, in cents; zero for a sale."""
    if intent.side is not Side.BUY:
        return ZERO
    fill_price = _estimated_price(intent, last_price, bar_volume, slippage)
    fill = Fill(intent.symbol, intent.side, intent.quantity, fill_price)
    return fill.notional + costs.cost(intent.quantity, fill.price).total


def validate_intent(
    intent: OrderIntent,
    state: PortfolioState,
    *,
    session: int,
    last_price: Decimal,
    bar_volume: Decimal,
    costs: CostModel,
    slippage: SlippageModel,
    reserved_cash: Decimal = ZERO,
    reserved_shares: int = 0,
) -> Rejection | None:
    """``None`` when the intent may be placed at ``session``, else the reason it may not.

    ``last_price`` and ``bar_volume`` are from the symbol's latest bar at ``session``.
    ``reserved_cash`` and ``reserved_shares`` are what earlier orders of the portfolio
    (same symbol for shares) have already committed."""
    if intent.side is Side.BUY:
        needed = required_cash(
            intent, last_price=last_price, bar_volume=bar_volume, costs=costs, slippage=slippage
        )
        available = state.cash - reserved_cash
        if needed > available:
            return Rejection(
                intent,
                session,
                RejectReason.INSUFFICIENT_CASH,
                f"needs {needed}, available cash is {available}",
            )
        return None
    held = state.positions.get(intent.symbol)
    available_shares = (held.quantity if held else 0) - reserved_shares
    if intent.quantity > available_shares:
        return Rejection(
            intent,
            session,
            RejectReason.INSUFFICIENT_POSITION,
            f"selling {intent.quantity} {intent.symbol}, {available_shares} available",
        )
    return None


def limit_reference(side: Side, limit_price: Decimal, bar: Bar) -> Decimal | None:
    """The price a limit order fills at before slippage on ``bar``, or ``None`` when the
    session range does not reach it: the open on a gap through the limit, else the limit."""
    limit = price(limit_price)
    if side is Side.BUY:
        if bar.open <= limit:
            return price(bar.open)
        return limit if bar.low <= limit else None
    if bar.open >= limit:
        return price(bar.open)
    return limit if bar.high >= limit else None


def process_order(
    order: Order,
    *,
    session: int,
    bar: Bar | None,
    state: PortfolioState,
    costs: CostModel,
    slippage: SlippageModel,
) -> Outcome:
    """What ``session`` does to an open order, given the symbol's bar for that session
    (``None`` when it has none) and the portfolio before the fill."""
    if order.status is not OrderStatus.OPEN:
        raise ValueError(f"order {order.order_id} is {order.status}, not open")
    intent = order.intent
    if bar is not None and (bar.symbol != intent.symbol or bar.session != session):
        raise ValueError(f"bar {bar.symbol}@{bar.session} is not {intent.symbol}@{session}")
    if session <= order.placed_session:
        return None
    if intent.order_type is OrderType.MARKET:
        if bar is None:
            return Rejection(intent, session, RejectReason.NO_PRICE, "no bar at the fill session")
        return _execute(order, session, price(bar.open), bar.volume, state, costs, slippage)

    last = order.expires_session
    if last is not None and session > last:
        return Expiry(order.order_id, session)
    if bar is not None and intent.limit_price is not None:
        reference = limit_reference(intent.side, intent.limit_price, bar)
        if reference is not None:
            return _execute(order, session, reference, bar.volume, state, costs, slippage)
    if last is not None and session >= last:
        return Expiry(order.order_id, session)
    return None


def _execute(
    order: Order,
    session: int,
    reference: Decimal,
    bar_volume: Decimal,
    state: PortfolioState,
    costs: CostModel,
    slippage: SlippageModel,
) -> Execution | Rejection:
    intent = order.intent
    fill_price = slippage.fill_price(intent.side, intent.quantity, reference, bar_volume)
    if intent.limit_price is not None:
        if intent.side is Side.BUY:
            fill_price = min(fill_price, intent.limit_price)
        else:
            fill_price = max(fill_price, intent.limit_price)
    breakdown = costs.cost(intent.quantity, fill_price)
    fill = Fill(intent.symbol, intent.side, intent.quantity, fill_price, breakdown.total)
    try:
        apply_fill(state, fill)
    except AccountingError as exc:
        reason = (
            RejectReason.INSUFFICIENT_POSITION
            if isinstance(exc, InsufficientPosition)
            else RejectReason.INSUFFICIENT_CASH
        )
        return Rejection(intent, session, reason, str(exc))
    return Execution(
        order_id=order.order_id,
        session=session,
        reference_price=reference,
        slippage=abs(fill.price - reference),
        costs=breakdown,
        fill=fill,
    )
