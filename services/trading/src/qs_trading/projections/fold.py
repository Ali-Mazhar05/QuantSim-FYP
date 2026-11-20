"""The projections of the trade log, folded from its events (task A15, A-FR-11, A-FR-15).

Every table next to ``trade_event`` is a projection of it. This module is the only place
that says how an event becomes projection rows; the engine store writes what :func:`fold`
returns for each session, and the rebuild folds the whole log from ``seq = 1`` with the
same function, so the live rows and the rebuilt rows cannot drift apart.

**What each event projects to**

- ``RUN_STARTED``: opens the books with the run's initial capital.
- ``TICK``: the session the following events belong to (``last_session``).
- ``ORDER_PLACED``: an ``order`` row, status ``open``.
- ``ORDER_FILLED``: the fill applied to the books
  (:func:`~qs_trading.domain.accounting.apply_fill`, exactly as the engine applies it), a
  ``fill`` row, a ``holding_history`` row with the symbol's quantity and cost basis after
  the fill (zero and zero when it closes the position), and the order's status ``filled``.
- ``ORDER_EXPIRED`` / ``ORDER_REJECTED`` with an ``order_id``: the order's status.
- ``VALUED``: a ``portfolio_value`` row.
- ``RUN_COMPLETED``: nothing.

After the events, the :class:`Ledger` gives the ``portfolio_state_current`` row:
``last_seq``, ``last_hash``, ``last_session``, cash and the positions cache
``{"<symbol>": {"quantity": <int>, "cost_basis": "<cents>"}}``.

The fold checks the log against itself as it goes: ``seq`` must follow on, ``prev_hash``
must name the previous event, a fill's ``cash_after`` and a valuation's cash must equal the
books. Any break raises :class:`ProjectionError`.
"""

import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from decimal import Decimal
from types import MappingProxyType
from typing import Any

from qs_trading.domain.accounting import (
    ZERO,
    AccountingError,
    Fill,
    PortfolioState,
    Position,
    apply_fill,
    open_portfolio,
)
from qs_trading.domain.events import (
    PAYLOADS,
    EventType,
    OrderExpiredV1,
    OrderFilledV1,
    OrderPlacedV1,
    OrderRejectedV1,
    Payload,
    RunStartedV1,
    TickV1,
    ValuedV1,
)
from qs_trading.domain.orders import OrderStatus

__all__ = [
    "Ledger",
    "PortfolioSnapshot",
    "ProjectedEvent",
    "Projection",
    "ProjectionError",
    "ProjectionRows",
    "Row",
    "fold",
    "parse_payload",
    "positions_json",
    "project_log",
    "snapshot_at",
]

Row = dict[str, Any]
"""One projection row: column name to value, as inserted into (and read from) its table."""


class ProjectionError(ValueError):
    """The log cannot be folded: it breaks its own chain or its own books."""

    def __init__(self, seq: int, message: str) -> None:
        super().__init__(f"seq {seq}: {message}")
        self.seq = seq


def parse_payload(event_type: str, version: int, payload: Mapping[str, Any]) -> Payload:
    """The payload model of a stored event (its JSONB payload as read back)."""
    try:
        model = PAYLOADS[(EventType(event_type), version)]
    except (KeyError, ValueError) as exc:
        raise ValueError(f"no payload model for {event_type} v{version}") from exc
    return model.model_validate(payload)


@dataclass(frozen=True, slots=True)
class ProjectedEvent:
    """What the fold reads of one log event: its place in the chain and its payload."""

    seq: int
    prev_hash: str | None
    hash: str
    payload: Payload

    @classmethod
    def from_stored(
        cls,
        *,
        seq: int,
        prev_hash: str | None,
        hash: str,
        event_type: str,
        version: int,
        payload: Mapping[str, Any],
    ) -> "ProjectedEvent":
        """From a ``trade_event`` row (refuses a payload no model reads)."""
        try:
            parsed = parse_payload(event_type, version, payload)
        except ValueError as exc:
            raise ProjectionError(seq, str(exc)) from exc
        return cls(seq, prev_hash, hash, parsed)


def positions_json(positions: Mapping[str, Position]) -> dict[str, Any]:
    """The positions cache of ``portfolio_state_current``, symbols in order."""
    return {
        symbol: {"quantity": position.quantity, "cost_basis": str(position.cost_basis)}
        for symbol, position in sorted(positions.items())
    }


def _positions_from_json(data: Mapping[str, Any]) -> Mapping[str, Position]:
    return MappingProxyType(
        {
            symbol: Position(int(item["quantity"]), Decimal(str(item["cost_basis"])))
            for symbol, item in data.items()
        }
    )


@dataclass(frozen=True, slots=True)
class Ledger:
    """Where the fold stands: the books (``None`` until ``RUN_STARTED``) and the end of the
    chain folded so far."""

    portfolio_id: uuid.UUID
    books: PortfolioState | None = None
    last_seq: int = 0
    last_hash: str | None = None
    last_session: int | None = None

    @classmethod
    def from_state_row(cls, portfolio_id: uuid.UUID, row: Mapping[str, Any]) -> "Ledger":
        """The ledger the committed ``portfolio_state_current`` row describes, for folding
        the next session onto it (the engine store). It knows cash and positions, which is
        all the projection rows are derived from; realised P&L and costs are not in the
        row and read as zero."""
        last_seq = int(row["last_seq"])
        if last_seq == 0:
            return cls(portfolio_id)
        cash = Decimal(row["cash"])
        books = PortfolioState(
            initial_capital=cash,
            cash=cash,
            positions=_positions_from_json(row["positions"] or {}),
        )
        session = row["last_session"]
        return cls(
            portfolio_id,
            books,
            last_seq,
            row["last_hash"],
            None if session is None else int(session),
        )

    def state_row(self) -> Row | None:
        """The ``portfolio_state_current`` row (without ``updated_at``); ``None`` before
        the first event."""
        if self.books is None:
            return None
        return {
            "portfolio_id": self.portfolio_id,
            "last_seq": self.last_seq,
            "last_hash": self.last_hash,
            "last_session": self.last_session,
            "cash": self.books.cash,
            "positions": positions_json(self.books.positions),
        }


@dataclass(frozen=True, slots=True)
class ProjectionRows:
    """The rows some events add. ``orders`` are the orders they place, with their status
    after the events; ``status_changes`` move orders placed by earlier events."""

    orders: tuple[Row, ...] = ()
    status_changes: tuple[tuple[str, str], ...] = ()
    fills: tuple[Row, ...] = ()
    holdings: tuple[Row, ...] = ()
    values: tuple[Row, ...] = ()


class _Folder:
    def __init__(self, ledger: Ledger) -> None:
        self.ledger = ledger
        self.orders: dict[str, Row] = {}
        self.status_changes: list[tuple[str, str]] = []
        self.fills: list[Row] = []
        self.holdings: list[Row] = []
        self.values: list[Row] = []

    @property
    def portfolio_id(self) -> uuid.UUID:
        return self.ledger.portfolio_id

    def rows(self) -> ProjectionRows:
        return ProjectionRows(
            orders=tuple(self.orders.values()),
            status_changes=tuple(self.status_changes),
            fills=tuple(self.fills),
            holdings=tuple(self.holdings),
            values=tuple(self.values),
        )

    def _status(self, order_id: str, status: OrderStatus) -> None:
        placed = self.orders.get(order_id)
        if placed is not None:
            placed["status"] = status.value
        else:
            self.status_changes.append((order_id, status.value))

    def apply(self, event: ProjectedEvent) -> None:
        ledger = self.ledger
        seq = event.seq
        if seq != ledger.last_seq + 1:
            raise ProjectionError(seq, f"expected seq {ledger.last_seq + 1}")
        if event.prev_hash != ledger.last_hash:
            raise ProjectionError(seq, "prev_hash does not name the previous event")
        payload = event.payload
        books = ledger.books
        session = ledger.last_session
        if isinstance(payload, RunStartedV1):
            if books is not None:
                raise ProjectionError(seq, "RUN_STARTED after the run started")
            books = open_portfolio(payload.initial_capital)
        elif books is None:
            raise ProjectionError(seq, f"{payload.type} before RUN_STARTED")
        elif isinstance(payload, TickV1):
            session = payload.session
        elif isinstance(payload, OrderPlacedV1):
            self._placed(seq, payload)
        elif isinstance(payload, OrderFilledV1):
            books = self._filled(seq, payload, books)
        elif isinstance(payload, OrderExpiredV1):
            self._status(payload.order_id, OrderStatus.EXPIRED)
        elif isinstance(payload, OrderRejectedV1):
            if payload.order_id is not None:
                self._status(payload.order_id, OrderStatus.REJECTED)
        elif isinstance(payload, ValuedV1):
            self._valued(seq, payload, books)
        self.ledger = replace(
            ledger, books=books, last_seq=seq, last_hash=event.hash, last_session=session
        )

    def _placed(self, seq: int, payload: OrderPlacedV1) -> None:
        if payload.order_id in self.orders:
            raise ProjectionError(seq, f"order {payload.order_id} is placed twice")
        self.orders[payload.order_id] = {
            "portfolio_id": self.portfolio_id,
            "order_id": payload.order_id,
            "symbol": payload.symbol,
            "side": payload.side.value,
            "quantity": payload.quantity,
            "order_type": payload.order_type.value,
            "limit_price": payload.limit_price,
            "placed_seq": seq,
            "placed_session": payload.session,
            "expires_session": payload.expires_session,
            "status": OrderStatus.OPEN.value,
        }

    def _filled(self, seq: int, payload: OrderFilledV1, books: PortfolioState) -> PortfolioState:
        try:
            after = apply_fill(
                books,
                Fill(
                    payload.symbol,
                    payload.side,
                    payload.quantity,
                    payload.fill_price,
                    payload.cost_total,
                ),
            )
        except (AccountingError, ValueError, TypeError) as exc:
            raise ProjectionError(seq, f"the fill does not apply to the books: {exc}") from exc
        if after.cash != payload.cash_after:
            raise ProjectionError(
                seq, f"cash after the fill is {after.cash}, the event says {payload.cash_after}"
            )
        self.fills.append(
            {
                "portfolio_id": self.portfolio_id,
                "seq": seq,
                "order_id": payload.order_id,
                "session": payload.session,
                "symbol": payload.symbol,
                "side": payload.side.value,
                "quantity": payload.quantity,
                "reference_price": payload.reference_price,
                "fill_price": payload.fill_price,
                "slippage": payload.slippage,
                "cost_fixed": payload.cost_fixed,
                "cost_per_share": payload.cost_per_share,
                "cost_percentage": payload.cost_percentage,
                "cost_total": payload.cost_total,
                "cash_after": payload.cash_after,
            }
        )
        held = after.positions.get(payload.symbol)
        self.holdings.append(
            {
                "portfolio_id": self.portfolio_id,
                "seq": seq,
                "symbol": payload.symbol,
                "session": payload.session,
                "quantity": held.quantity if held else 0,
                "cost_basis": held.cost_basis if held else ZERO,
            }
        )
        self._status(payload.order_id, OrderStatus.FILLED)
        return after

    def _valued(self, seq: int, payload: ValuedV1, books: PortfolioState) -> None:
        if payload.cash != books.cash:
            raise ProjectionError(
                seq, f"valued with cash {payload.cash}, the books hold {books.cash}"
            )
        self.values.append(
            {
                "portfolio_id": self.portfolio_id,
                "ts": payload.ts,
                "session": payload.session,
                "seq": seq,
                "cash": payload.cash,
                "market_value": payload.market_value,
                "value": payload.portfolio_value,
                "realised_pnl": payload.realised_pnl,
                "unrealised_pnl": payload.unrealised_pnl,
                "total_costs": payload.total_costs,
            }
        )


def fold(ledger: Ledger, events: Iterable[ProjectedEvent]) -> tuple[Ledger, ProjectionRows]:
    """Folds ``events`` (the next ones in the chain) onto ``ledger``: the ledger after them
    and the projection rows they add."""
    folder = _Folder(ledger)
    for event in events:
        folder.apply(event)
    return folder.ledger, folder.rows()


@dataclass(frozen=True, slots=True)
class Projection:
    """Every projection of one portfolio's log, keyed as each table is: orders by
    ``order_id``, fills, holdings and values by ``seq`` (holdings by ``(seq, symbol)``),
    and the ``portfolio_state_current`` row (``None`` for an empty log)."""

    orders: Mapping[str, Row] = field(default_factory=dict)
    fills: Mapping[int, Row] = field(default_factory=dict)
    holdings: Mapping[tuple[int, str], Row] = field(default_factory=dict)
    values: Mapping[int, Row] = field(default_factory=dict)
    state: Row | None = None

    @classmethod
    def from_rows(cls, rows: ProjectionRows, state: Row | None) -> "Projection":
        return cls(
            orders={row["order_id"]: row for row in rows.orders},
            fills={row["seq"]: row for row in rows.fills},
            holdings={(row["seq"], row["symbol"]): row for row in rows.holdings},
            values={row["seq"]: row for row in rows.values},
            state=state,
        )


def project_log(
    portfolio_id: uuid.UUID, events: Iterable[ProjectedEvent]
) -> tuple[Ledger, ProjectionRows]:
    """The whole log folded from ``seq = 1``. Every status change must then name an order
    the log placed."""
    ledger, rows = fold(Ledger(portfolio_id), events)
    if rows.status_changes:
        order_id, status = rows.status_changes[0]
        raise ProjectionError(ledger.last_seq, f"order {order_id} is {status} but never placed")
    return ledger, rows


@dataclass(frozen=True, slots=True)
class PortfolioSnapshot:
    """A portfolio's state right after the event at ``seq`` (A-FR-15)."""

    portfolio_id: uuid.UUID
    seq: int
    hash: str
    session: int | None
    initial_capital: Decimal
    cash: Decimal
    positions: Mapping[str, Position]
    realised_pnl: Decimal
    total_costs: Decimal
    open_orders: tuple[str, ...]
    last_value: Decimal | None  # the latest valuation at or before ``seq``
    last_valued_seq: int | None

    def state_row(self) -> Row:
        """What ``portfolio_state_current`` holds when the log ends at ``seq``."""
        return {
            "portfolio_id": self.portfolio_id,
            "last_seq": self.seq,
            "last_hash": self.hash,
            "last_session": self.session,
            "cash": self.cash,
            "positions": positions_json(self.positions),
        }

    def to_json(self) -> dict[str, Any]:
        return {
            "portfolio_id": str(self.portfolio_id),
            "seq": self.seq,
            "hash": self.hash,
            "session": self.session,
            "initial_capital": str(self.initial_capital),
            "cash": str(self.cash),
            "positions": positions_json(self.positions),
            "realised_pnl": str(self.realised_pnl),
            "total_costs": str(self.total_costs),
            "open_orders": list(self.open_orders),
            "last_value": None if self.last_value is None else str(self.last_value),
            "last_valued_seq": self.last_valued_seq,
        }


def snapshot_at(
    portfolio_id: uuid.UUID, events: Sequence[ProjectedEvent], seq: int
) -> PortfolioSnapshot:
    """The state after the event at ``seq``, folding the log (from ``seq = 1``) up to it.
    Raises ``LookupError`` when the log does not reach ``seq``."""
    prefix = [event for event in events if event.seq <= seq]
    if seq < 1 or not prefix or prefix[-1].seq != seq:
        raise LookupError(f"portfolio {portfolio_id} has no event at seq {seq}")
    ledger, rows = project_log(portfolio_id, prefix)
    books = ledger.books
    if books is None or ledger.last_hash is None:
        raise ProjectionError(seq, "the log does not start with RUN_STARTED")
    last = rows.values[-1] if rows.values else None
    return PortfolioSnapshot(
        portfolio_id=portfolio_id,
        seq=ledger.last_seq,
        hash=ledger.last_hash,
        session=ledger.last_session,
        initial_capital=books.initial_capital,
        cash=books.cash,
        positions=books.positions,
        realised_pnl=books.realised_pnl,
        total_costs=books.total_costs,
        open_orders=tuple(
            row["order_id"] for row in rows.orders if row["status"] == OrderStatus.OPEN.value
        ),
        last_value=None if last is None else last["value"],
        last_valued_seq=None if last is None else last["seq"],
    )
