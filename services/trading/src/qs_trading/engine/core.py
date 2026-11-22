"""The pure engine core (task A14): one session of one portfolio at a time, no I/O, no
clock, no randomness, so the same spec on the same ticks always gives the same events and
the same final hash (A-FR-12) and a crashed run can be recomputed exactly (A-FR-13).

**Order of one session** (lane guide, "Engine loop, per session"), each step appending its
events to the log in this order:

1. ``RUN_STARTED`` (first session only): the full spec and the source fingerprint.
2. ``TICK``: the session index, its close time and the source ``seq`` range consumed.
3. Open orders, oldest first (by placement ``seq``), against this session's bar of their
   symbol (:func:`~qs_trading.domain.execution.process_order`): market orders placed at
   the previous session fill at this open, resting limits fill when the range crosses or
   expire. Each gives ``ORDER_FILLED`` (applied to the books at once, so a sale placed
   before a buy pays for it), ``ORDER_REJECTED`` (with the ``order_id``) or
   ``ORDER_EXPIRED``; an order that keeps resting gives nothing.
4. The strategy's ``on_bar`` on a history-only view of sessions ``<= t`` and the
   portfolio after step 3.
5. Each intent, in the strategy's order, is validated
   (:func:`~qs_trading.domain.execution.validate_intent`) against the books and what open
   orders already commit: resting and new buys reserve their
   :func:`~qs_trading.domain.execution.required_cash`, sales reserve their shares, and a
   market sale placed this session credits its estimated proceeds (at the close, after
   slippage and costs) to the buys after it, because the strategies size buys that way
   and sales fill first at the next open. ``ORDER_PLACED`` or ``ORDER_REJECTED``.
6. ``VALUED`` at the close: every position at its latest close at or before ``t``,
   market value rounded to cents.
7. ``RUN_COMPLETED`` (last session only).

**Determinism.** ``event_time`` of every event is the session's close time from the ticks
(``RUN_STARTED`` takes the first session's, ``RUN_COMPLETED`` the last one's). Order ids
are ``"<portfolio_id>:<seq>"``, ``seq`` being that of the order's ``ORDER_PLACED``.
"""

import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from itertools import pairwise
from typing import Any

from qs_trading.domain.accounting import ZERO, PortfolioState, Side, apply_fill, open_portfolio
from qs_trading.domain.accounting import market_value as books_market_value
from qs_trading.domain.costs import LinearCostModel, cost_model_from_json
from qs_trading.domain.events import (
    EventType,
    OrderExpiredV1,
    OrderFilledV1,
    OrderPlacedV1,
    OrderRejectedV1,
    Payload,
    RunCompletedV1,
    RunStartedV1,
    TickV1,
    ValuedV1,
)
from qs_trading.domain.execution import (
    Expiry,
    place_order,
    process_order,
    required_cash,
    validate_intent,
)
from qs_trading.domain.hashing import event_hash, payload_json
from qs_trading.domain.history import BarHistory, InMemoryHistoryView
from qs_trading.domain.money import cents
from qs_trading.domain.orders import (
    Execution,
    Order,
    OrderIntent,
    OrderType,
    Rejection,
    RejectReason,
)
from qs_trading.domain.slippage import (
    FixedBpsSlippage,
    SlippageModel,
    VolumeSlippage,
    slippage_model_from_json,
)
from qs_trading.domain.strategies import build_strategy, validate_params
from qs_trading.domain.strategy import Bar, Strategy
from qs_trading.ports.market_environment import EnvironmentRef, Tick

__all__ = [
    "Engine",
    "EngineError",
    "EngineState",
    "LoggedEvent",
    "ResumeMismatch",
    "RunSpec",
    "SessionResult",
    "SessionTicks",
    "group_sessions",
    "order_id_for",
    "slippage_from_json",
]


class EngineError(RuntimeError):
    """The engine cannot run this spec on these ticks."""


class ResumeMismatch(EngineError):
    """Recomputing a run did not reproduce the log already committed."""


@dataclass(frozen=True, slots=True)
class RunSpec:
    """What a portfolio runs: everything ``RUN_STARTED`` records except the fingerprint.
    ``cost_model`` and ``slippage_model`` are the portfolio's stored JSON."""

    portfolio_id: uuid.UUID
    strategy_kind: str
    strategy_params: Mapping[str, Any]
    initial_capital: Decimal
    cost_model: Mapping[str, Any]
    slippage_model: Mapping[str, Any]
    environment: EnvironmentRef


@dataclass(frozen=True, slots=True)
class LoggedEvent:
    """One row of the trade log, hash-chained onto the one before."""

    portfolio_id: uuid.UUID
    seq: int
    event_time: datetime
    payload: Payload
    prev_hash: str | None
    hash: str

    @property
    def type(self) -> EventType:
        return self.payload.type

    @property
    def version(self) -> int:
        return self.payload.version

    @property
    def payload_json(self) -> dict[str, Any]:
        """The stored (and hashed) form of the payload."""
        return payload_json(self.payload)


@dataclass(frozen=True, slots=True)
class SessionTicks:
    """Every tick of one session, in ``(session, symbol)`` order."""

    session: int
    ts: datetime
    ticks: tuple[Tick, ...]

    @property
    def first_seq(self) -> int:
        return self.ticks[0].seq

    @property
    def last_seq(self) -> int:
        return self.ticks[-1].seq


@dataclass(frozen=True, slots=True)
class EngineState:
    """Where a run stands after a whole number of sessions."""

    portfolio: PortfolioState
    open_orders: tuple[Order, ...] = ()
    last_seq: int = 0
    last_hash: str | None = None
    sessions_done: int = 0
    last_value: Decimal | None = None
    completed: bool = False


@dataclass(frozen=True, slots=True)
class SessionResult:
    """The events one session appended and the state after it."""

    index: int
    session: int
    events: tuple[LoggedEvent, ...]
    state: EngineState


def order_id_for(portfolio_id: uuid.UUID, seq: int) -> str:
    """The id of the order placed by the event at ``seq``."""
    return f"{portfolio_id}:{seq}"


def slippage_from_json(data: Mapping[str, Any]) -> FixedBpsSlippage | VolumeSlippage:
    """The portfolio's slippage model; an empty object (the column default) is no
    slippage."""
    if not data:
        return FixedBpsSlippage()
    return slippage_model_from_json(data)


def _bar(tick: Tick) -> Bar:
    return Bar(
        session=tick.session,
        symbol=tick.symbol,
        ts=tick.ts,
        open=tick.open,
        high=tick.high,
        low=tick.low,
        close=tick.close,
        volume=tick.volume,
    )


def group_sessions(ticks: Iterable[Tick]) -> tuple[SessionTicks, ...]:
    """Ticks grouped by session. Refuses an empty feed, a ``seq`` that does not run 1, 2,
    3 without gaps, and ticks out of ``(session, symbol)`` order (ADR 01)."""
    ordered = tuple(ticks)
    if not ordered:
        raise EngineError("the environment served no ticks")
    for expected, tick in enumerate(ordered, start=1):
        if tick.seq != expected:
            raise EngineError(f"tick seq must run 1, 2, 3 without gaps: expected {expected}")
    for before, after in pairwise(ordered):
        if (before.session, before.symbol) >= (after.session, after.symbol):
            raise EngineError(f"ticks are not in (session, symbol) order at seq {after.seq}")
    sessions: list[SessionTicks] = []
    current: list[Tick] = []
    for tick in ordered:
        if current and tick.session != current[0].session:
            sessions.append(SessionTicks(current[0].session, current[-1].ts, tuple(current)))
            current = []
        current.append(tick)
    sessions.append(SessionTicks(current[0].session, current[-1].ts, tuple(current)))
    for day in sessions:
        if any(t.ts != day.ts for t in day.ticks):
            raise EngineError(f"the ticks of session {day.session} disagree on its close time")
    return tuple(sessions)


class _Log:
    """Appends events to the chain, giving each its ``seq`` and hash."""

    def __init__(self, portfolio_id: uuid.UUID, last_seq: int, last_hash: str | None) -> None:
        self.portfolio_id = portfolio_id
        self.last_seq = last_seq
        self.last_hash = last_hash
        self.events: list[LoggedEvent] = []

    @property
    def next_seq(self) -> int:
        return self.last_seq + 1

    def append(self, payload: Payload, event_time: datetime) -> LoggedEvent:
        seq = self.next_seq
        digest = event_hash(
            self.last_hash,
            portfolio_id=self.portfolio_id,
            seq=seq,
            event_type=payload.type,
            version=payload.version,
            payload=payload_json(payload),
            event_time=event_time,
        )
        event = LoggedEvent(self.portfolio_id, seq, event_time, payload, self.last_hash, digest)
        self.events.append(event)
        self.last_seq, self.last_hash = seq, digest
        return event


def _rejected(rejection: Rejection, order_id: str | None = None) -> OrderRejectedV1:
    intent = rejection.intent
    return OrderRejectedV1(
        session=rejection.session,
        symbol=intent.symbol,
        side=intent.side,
        quantity=intent.quantity,
        order_type=intent.order_type,
        limit_price=intent.limit_price,
        reason=rejection.reason,
        detail=rejection.detail,
        order_id=order_id,
    )


def _filled(execution: Execution, cash_after: Decimal) -> OrderFilledV1:
    fill = execution.fill
    return OrderFilledV1(
        order_id=execution.order_id,
        session=execution.session,
        symbol=fill.symbol,
        side=fill.side,
        quantity=fill.quantity,
        reference_price=execution.reference_price,
        fill_price=fill.price,
        slippage=execution.slippage,
        cost_fixed=execution.costs.fixed,
        cost_per_share=execution.costs.per_share,
        cost_percentage=execution.costs.percentage,
        cost_total=execution.costs.total,
        cash_after=cash_after,
    )


@dataclass(frozen=True, eq=False)
class Engine:
    """One portfolio's run over one environment's ticks. Build it with :meth:`prepare`."""

    spec: RunSpec
    fingerprint: str
    sessions: tuple[SessionTicks, ...]
    history: BarHistory
    strategy: Strategy
    costs: LinearCostModel
    slippage: SlippageModel
    run_started: RunStartedV1
    _bars: tuple[Mapping[str, Bar], ...] = field(repr=False)

    @classmethod
    def prepare(
        cls,
        spec: RunSpec,
        fingerprint: str,
        ticks: Iterable[Tick],
        *,
        strategy: Strategy | None = None,
    ) -> "Engine":
        """Validates the spec (strategy parameters, cost and slippage models) and the
        ticks, and freezes the ``RUN_STARTED`` payload. The strategy is built from the
        spec's ``kind`` and ``params``; ``strategy`` replaces it (tests that need orders
        no built-in kind sends, such as limits)."""
        if not fingerprint:
            raise EngineError("a run needs the source fingerprint")
        sessions = group_sessions(ticks)
        params = validate_params(spec.strategy_kind, spec.strategy_params)
        costs = cost_model_from_json(spec.cost_model)
        slippage = slippage_from_json(spec.slippage_model)
        capital = open_portfolio(spec.initial_capital).initial_capital
        run_started = RunStartedV1(
            strategy_kind=spec.strategy_kind,
            strategy_params=params.model_dump(mode="json"),
            initial_capital=capital,
            cost_model=costs.to_json(),
            slippage_model=slippage.to_json(),
            env_type=spec.environment.env_type,
            env_id=spec.environment.env_id,
            path_index=spec.environment.path_index,
            source_fingerprint=fingerprint,
        )
        bars = tuple({t.symbol: _bar(t) for t in day.ticks} for day in sessions)
        return cls(
            spec=spec,
            fingerprint=fingerprint,
            sessions=sessions,
            history=BarHistory(bar for day in bars for bar in day.values()),
            strategy=strategy or build_strategy(spec.strategy_kind, spec.strategy_params),
            costs=costs,
            slippage=slippage,
            run_started=run_started,
            _bars=bars,
        )

    def initial_state(self) -> EngineState:
        """The state before the first session: only cash, an empty log."""
        return EngineState(portfolio=open_portfolio(self.spec.initial_capital))

    def step(self, state: EngineState, index: int) -> SessionResult:
        """Runs session number ``index`` (0-based position in :attr:`sessions`) on
        ``state``, which must be the state after the sessions before it."""
        if state.completed:
            raise EngineError("the run is already complete")
        if index != state.sessions_done or not 0 <= index < len(self.sessions):
            raise EngineError(f"session {index} cannot follow {state.sessions_done} sessions")
        day = self.sessions[index]
        log = _Log(self.spec.portfolio_id, state.last_seq, state.last_hash)
        if index == 0:
            log.append(self.run_started, day.ts)
        log.append(
            TickV1(
                session=day.session,
                ts=day.ts,
                first_tick_seq=day.first_seq,
                last_tick_seq=day.last_seq,
            ),
            day.ts,
        )
        portfolio, resting = self._process_open_orders(state, day, self._bars[index], log)
        view = self.history.view(day.session, portfolio)
        intents = self.strategy.on_bar(view)
        open_orders = self._place(intents, view, resting, day, log)
        valued = self._value(view, day)
        log.append(valued, day.ts)
        final = index == len(self.sessions) - 1
        if final:
            log.append(
                RunCompletedV1(sessions=len(self.sessions), final_value=valued.portfolio_value),
                day.ts,
            )
        return SessionResult(
            index=index,
            session=day.session,
            events=tuple(log.events),
            state=EngineState(
                portfolio=portfolio,
                open_orders=open_orders,
                last_seq=log.last_seq,
                last_hash=log.last_hash,
                sessions_done=index + 1,
                last_value=valued.portfolio_value,
                completed=final,
            ),
        )

    def run(self) -> tuple[SessionResult, ...]:
        """Every session from the start, in memory."""
        results: list[SessionResult] = []
        state = self.initial_state()
        for index in range(len(self.sessions)):
            result = self.step(state, index)
            results.append(result)
            state = result.state
        return tuple(results)

    def replay(self, last_seq: int, last_hash: str | None) -> tuple[EngineState, int]:
        """Recomputes the run from session 0, writing nothing, up to the committed
        ``last_seq``. Returns the state there and the index of the next session to run.
        Raises :class:`ResumeMismatch` when the recomputed chain does not end exactly on
        ``last_seq`` with hash ``last_hash``."""
        state = self.initial_state()
        index = 0
        while state.last_seq < last_seq and index < len(self.sessions):
            state = self.step(state, index).state
            index += 1
        if state.last_seq != last_seq or state.last_hash != last_hash:
            raise ResumeMismatch(
                f"recomputing portfolio {self.spec.portfolio_id} gave seq {state.last_seq}"
                f" with hash {state.last_hash}, but the log holds seq {last_seq} with hash"
                f" {last_hash}: the spec or the market data changed since the run started"
            )
        return state, index

    # --- the steps of a session ---------------------------------------------------------

    def _process_open_orders(
        self,
        state: EngineState,
        day: SessionTicks,
        bars: Mapping[str, Bar],
        log: _Log,
    ) -> tuple[PortfolioState, list[Order]]:
        portfolio = state.portfolio
        resting: list[Order] = []
        for order in state.open_orders:
            outcome = process_order(
                order,
                session=day.session,
                bar=bars.get(order.intent.symbol),
                state=portfolio,
                costs=self.costs,
                slippage=self.slippage,
            )
            if outcome is None:
                resting.append(order)
            elif isinstance(outcome, Execution):
                portfolio = apply_fill(portfolio, outcome.fill)
                log.append(_filled(outcome, portfolio.cash), day.ts)
            elif isinstance(outcome, Rejection):
                log.append(_rejected(outcome, order.order_id), day.ts)
            elif isinstance(outcome, Expiry):
                log.append(OrderExpiredV1(order_id=outcome.order_id, session=day.session), day.ts)
        return portfolio, resting

    def _reserved_by(self, order: Order) -> Decimal:
        intent = order.intent
        reference = intent.limit_price
        if intent.side is not Side.BUY or reference is None:
            return ZERO
        return required_cash(
            intent,
            last_price=reference,
            bar_volume=Decimal(0),
            costs=self.costs,
            slippage=self.slippage,
        )

    def _sale_proceeds(self, intent: OrderIntent, latest: Bar) -> Decimal:
        """What a market sale is expected to bring in: notional at the slipped close,
        less its costs, in cents."""
        fill_price = self.slippage.fill_price(
            Side.SELL, intent.quantity, latest.close, latest.volume
        )
        notional = cents(intent.quantity * fill_price)
        return notional - self.costs.cost(intent.quantity, fill_price).total

    def _place(
        self,
        intents: Sequence[OrderIntent],
        view: InMemoryHistoryView,
        resting: list[Order],
        day: SessionTicks,
        log: _Log,
    ) -> tuple[Order, ...]:
        portfolio = view.portfolio
        orders = list(resting)
        reserved_cash = sum((self._reserved_by(order) for order in resting), ZERO)
        reserved_shares: dict[str, int] = {}
        for order in resting:
            if order.intent.side is Side.SELL:
                symbol = order.intent.symbol
                reserved_shares[symbol] = reserved_shares.get(symbol, 0) + order.intent.quantity
        for intent in intents:
            symbol = intent.symbol
            if symbol not in self.history.symbols:
                rejection = Rejection(
                    intent, day.session, RejectReason.UNKNOWN_SYMBOL, f"{symbol} is not traded"
                )
                log.append(_rejected(rejection), day.ts)
                continue
            latest = view.latest(symbol)
            if latest is None:
                rejection = Rejection(
                    intent, day.session, RejectReason.NO_PRICE, f"{symbol} has no bar yet"
                )
                log.append(_rejected(rejection), day.ts)
                continue
            refused = validate_intent(
                intent,
                portfolio,
                session=day.session,
                last_price=latest.close,
                bar_volume=latest.volume,
                costs=self.costs,
                slippage=self.slippage,
                reserved_cash=reserved_cash,
                reserved_shares=reserved_shares.get(symbol, 0),
            )
            if refused is not None:
                log.append(_rejected(refused), day.ts)
                continue
            seq = log.next_seq
            order = place_order(
                intent,
                order_id=order_id_for(self.spec.portfolio_id, seq),
                seq=seq,
                session=day.session,
            )
            log.append(
                OrderPlacedV1(
                    order_id=order.order_id,
                    session=day.session,
                    symbol=symbol,
                    side=intent.side,
                    quantity=intent.quantity,
                    order_type=intent.order_type,
                    limit_price=intent.limit_price,
                    expires_session=order.expires_session,
                ),
                day.ts,
            )
            orders.append(order)
            if intent.side is Side.BUY:
                reserved_cash += required_cash(
                    intent,
                    last_price=latest.close,
                    bar_volume=latest.volume,
                    costs=self.costs,
                    slippage=self.slippage,
                )
            else:
                reserved_shares[symbol] = reserved_shares.get(symbol, 0) + intent.quantity
                if intent.order_type is OrderType.MARKET:
                    reserved_cash -= self._sale_proceeds(intent, latest)
        return tuple(orders)

    def _value(self, view: InMemoryHistoryView, day: SessionTicks) -> ValuedV1:
        portfolio = view.portfolio
        marks: dict[str, Decimal] = {}
        for symbol in portfolio.positions:
            latest = view.latest(symbol)
            if latest is not None:
                marks[symbol] = latest.close
        market = cents(books_market_value(portfolio, marks))
        basis = sum((p.cost_basis for p in portfolio.positions.values()), ZERO)
        return ValuedV1(
            session=day.session,
            ts=day.ts,
            cash=portfolio.cash,
            market_value=market,
            portfolio_value=portfolio.cash + market,
            realised_pnl=portfolio.realised_pnl,
            unrealised_pnl=market - basis,
            total_costs=portfolio.total_costs,
        )
