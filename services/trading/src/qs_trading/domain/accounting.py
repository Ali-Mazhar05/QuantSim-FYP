"""Portfolio accounting core (task A10).

Pure functions over immutable state: long only, whole shares, one currency (USD).

Each position keeps its cost basis in cents. A buy adds the rounded notional to the
basis; a sale releases basis in proportion to the shares sold (the whole basis when the
position closes) and books the difference as realised P&L. Costs are paid from cash and
never added to the basis. Because every cash movement and every basis movement is the
same rounded number, the P&L identity holds exactly, with no rounding residue:

    portfolio_value - initial_capital == realised + unrealised - costs

where ``portfolio_value = cash + sum(qty * mark)`` and
``unrealised = sum(qty * mark - basis)``.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import ROUND_HALF_EVEN, Decimal
from enum import StrEnum
from types import MappingProxyType

from qs_trading.domain.money import PRICE_STEP, Amount, cents, price

ZERO = Decimal("0.00")


class Side(StrEnum):
    BUY = "buy"
    SELL = "sell"


class AccountingError(ValueError):
    """A fill that the books cannot accept; the state is left unchanged."""


class InsufficientCash(AccountingError):
    """The fill would make cash negative."""


class InsufficientPosition(AccountingError):
    """A sale of more shares than are held (the engine is long only)."""


class MissingMark(AccountingError):
    """A held instrument has no price to value it at."""


@dataclass(frozen=True, slots=True)
class Fill:
    """One executed trade: whole shares at a price, plus the cost paid for it."""

    symbol: str
    side: Side
    quantity: int
    price: Decimal
    cost: Decimal = ZERO

    def __post_init__(self) -> None:
        if not self.symbol:
            raise ValueError("a fill needs a symbol")
        if isinstance(self.quantity, bool) or not isinstance(self.quantity, int):
            raise TypeError("quantity must be a whole number of shares")
        if self.quantity <= 0:
            raise ValueError(f"quantity must be above zero, got {self.quantity}")
        object.__setattr__(self, "side", Side(self.side))
        object.__setattr__(self, "price", price(self.price))
        cost = cents(self.cost)
        if cost < 0:
            raise ValueError(f"cost cannot be negative, got {cost}")
        object.__setattr__(self, "cost", cost)

    @property
    def notional(self) -> Decimal:
        """Quantity times price, rounded to cents."""
        return cents(self.quantity * self.price)


@dataclass(frozen=True, slots=True)
class Position:
    """Shares held in one instrument and what they cost, in cents."""

    quantity: int
    cost_basis: Decimal

    @property
    def average_cost(self) -> Decimal:
        """Cost basis per share, to 8 decimal places."""
        return (self.cost_basis / self.quantity).quantize(PRICE_STEP, rounding=ROUND_HALF_EVEN)


@dataclass(frozen=True, slots=True)
class PortfolioState:
    initial_capital: Decimal
    cash: Decimal
    positions: Mapping[str, Position] = field(default_factory=lambda: MappingProxyType({}))
    realised_pnl: Decimal = ZERO
    total_costs: Decimal = ZERO


def open_portfolio(capital: Amount) -> PortfolioState:
    """A new portfolio holding only cash."""
    amount = cents(capital)
    if amount <= 0:
        raise ValueError(f"starting capital must be above zero, got {amount}")
    return PortfolioState(initial_capital=amount, cash=amount)


def apply_fill(state: PortfolioState, fill: Fill) -> PortfolioState:
    """The state after ``fill``. Raises an ``AccountingError`` and changes nothing when
    the fill would leave cash negative or sell shares that are not held."""
    if fill.side is Side.BUY:
        return _buy(state, fill)
    return _sell(state, fill)


def _buy(state: PortfolioState, fill: Fill) -> PortfolioState:
    outlay = fill.notional + fill.cost
    if outlay > state.cash:
        raise InsufficientCash(
            f"buying {fill.quantity} {fill.symbol} needs {outlay}, cash is {state.cash}"
        )
    held = state.positions.get(fill.symbol)
    position = Position(
        quantity=(held.quantity if held else 0) + fill.quantity,
        cost_basis=(held.cost_basis if held else ZERO) + fill.notional,
    )
    return PortfolioState(
        initial_capital=state.initial_capital,
        cash=state.cash - outlay,
        positions=_with(state.positions, fill.symbol, position),
        realised_pnl=state.realised_pnl,
        total_costs=state.total_costs + fill.cost,
    )


def _sell(state: PortfolioState, fill: Fill) -> PortfolioState:
    held = state.positions.get(fill.symbol)
    if held is None or fill.quantity > held.quantity:
        owned = held.quantity if held else 0
        raise InsufficientPosition(f"selling {fill.quantity} {fill.symbol}, holding {owned}")
    proceeds = fill.notional
    cash = state.cash + proceeds - fill.cost
    if cash < 0:
        raise InsufficientCash(f"the cost {fill.cost} exceeds cash plus proceeds")
    if fill.quantity == held.quantity:
        released = held.cost_basis
        position = None
    else:
        released = cents(held.cost_basis * fill.quantity / held.quantity)
        position = Position(held.quantity - fill.quantity, held.cost_basis - released)
    return PortfolioState(
        initial_capital=state.initial_capital,
        cash=cash,
        positions=_with(state.positions, fill.symbol, position),
        realised_pnl=state.realised_pnl + proceeds - released,
        total_costs=state.total_costs + fill.cost,
    )


def _with(
    positions: Mapping[str, Position], symbol: str, position: Position | None
) -> Mapping[str, Position]:
    updated = dict(positions)
    if position is None:
        updated.pop(symbol, None)
    else:
        updated[symbol] = position
    return MappingProxyType(updated)


def _mark(marks: Mapping[str, Amount], symbol: str) -> Decimal:
    if symbol not in marks:
        raise MissingMark(f"no price to value {symbol} at")
    return price(marks[symbol])


def market_value(state: PortfolioState, marks: Mapping[str, Amount]) -> Decimal:
    """Sum of quantity times mark over every position (exact, not rounded)."""
    return sum((pos.quantity * _mark(marks, sym) for sym, pos in state.positions.items()), ZERO)


def portfolio_value(state: PortfolioState, marks: Mapping[str, Amount]) -> Decimal:
    """Cash plus market value (exact, not rounded)."""
    return state.cash + market_value(state, marks)


def unrealised_pnl(state: PortfolioState, marks: Mapping[str, Amount]) -> Decimal:
    """Sum of market value minus cost basis over every position."""
    return sum(
        (pos.quantity * _mark(marks, sym) - pos.cost_basis for sym, pos in state.positions.items()),
        ZERO,
    )
