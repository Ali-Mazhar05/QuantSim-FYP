"""Order sizing shared by the built-in strategies (task A12).

Rules, the same for every kind:

* **Prices.** A strategy sizes at the latest close at or before ``t`` (the order fills at
  the next open, which it cannot see).
* **Value.** Portfolio value is cash plus every position at that close; a held symbol with
  no bar yet is valued at its average cost.
* **Investable value.** ``(1 - cash_buffer) * value``. Target weights are fractions of
  it, so after the orders fill at the sizing prices at least ``cash_buffer`` of value is
  still cash for costs and slippage.
* **Whole shares.** A target value becomes ``floor(target / close)`` shares, rounded down,
  never up. Long only: a target is never below zero and a sale never exceeds the holding.
* **Order.** Sales come first, then buys, each in the environment's symbol order, so a
  rerun lists the same orders in the same order.
* **Budget.** Buys spend at most cash plus the proceeds of the sales, less the cash
  buffer, all at the sizing prices; a buy that does not fit is cut to the shares that do.

Arithmetic runs in a fixed decimal context (28 digits, half to even) so the result does
not depend on the caller's ``decimal`` context (A-FR-12).
"""

from collections.abc import Mapping
from decimal import ROUND_FLOOR, ROUND_HALF_EVEN, Context, Decimal, localcontext

from qs_trading.domain.accounting import Side
from qs_trading.domain.orders import OrderIntent
from qs_trading.domain.strategy import HistoryView

__all__ = [
    "DECIMAL_CONTEXT",
    "held",
    "investable",
    "latest_closes",
    "orders_toward",
    "portfolio_value",
    "whole_shares",
]

DECIMAL_CONTEXT = Context(prec=28, rounding=ROUND_HALF_EVEN)
ZERO = Decimal(0)


def latest_closes(view: HistoryView) -> dict[str, Decimal]:
    """The latest close at or before ``t`` of every symbol that has one."""
    closes: dict[str, Decimal] = {}
    for symbol in view.symbols:
        bar = view.latest(symbol)
        if bar is not None:
            closes[symbol] = bar.close
    return closes


def held(view: HistoryView, symbol: str) -> int:
    """Shares of ``symbol`` held after the fills of ``t``."""
    position = view.portfolio.positions.get(symbol)
    return position.quantity if position is not None else 0


def portfolio_value(view: HistoryView, closes: Mapping[str, Decimal]) -> Decimal:
    """Cash plus every position at its latest close (average cost when it has none)."""
    with localcontext(DECIMAL_CONTEXT):
        total = view.portfolio.cash
        for symbol, position in view.portfolio.positions.items():
            mark = closes.get(symbol, position.average_cost)
            total += position.quantity * mark
        return total


def investable(value: Decimal, cash_buffer: Decimal) -> Decimal:
    """The part of ``value`` a strategy may hold in positions."""
    with localcontext(DECIMAL_CONTEXT):
        return max(value, ZERO) * (1 - cash_buffer)


def whole_shares(target_value: Decimal, close: Decimal) -> int:
    """Shares worth at most ``target_value`` at ``close``, rounded down (zero when below
    one share or when the target is not positive)."""
    if target_value <= 0:
        return 0
    with localcontext(DECIMAL_CONTEXT):
        return int((target_value / close).to_integral_value(rounding=ROUND_FLOOR))


def orders_toward(
    view: HistoryView,
    targets: Mapping[str, int],
    closes: Mapping[str, Decimal],
    value: Decimal,
    cash_buffer: Decimal,
) -> tuple[OrderIntent, ...]:
    """Market orders that move each symbol in ``targets`` to its target share count.
    Symbols absent from ``targets`` are left as they are; a symbol without a close is
    skipped, since it can be neither sized nor valued."""
    sells: list[OrderIntent] = []
    buys: list[tuple[str, int]] = []
    with localcontext(DECIMAL_CONTEXT):
        budget = view.portfolio.cash - cash_buffer * max(value, ZERO)
        for symbol in view.symbols:
            if symbol not in targets or symbol not in closes:
                continue
            change = max(targets[symbol], 0) - held(view, symbol)
            if change < 0:
                sells.append(OrderIntent(symbol, Side.SELL, -change))
                budget += -change * closes[symbol]
            elif change > 0:
                buys.append((symbol, change))
        orders = list(sells)
        for symbol, wanted in buys:
            quantity = min(wanted, whole_shares(budget, closes[symbol]))
            if quantity > 0:
                orders.append(OrderIntent(symbol, Side.BUY, quantity))
                budget -= quantity * closes[symbol]
    return tuple(orders)
