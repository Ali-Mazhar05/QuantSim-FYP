"""trading_db persistence of an engine run (task A14).

:class:`PortfolioStore` is the :class:`~qs_trading.engine.runner.EventSink` of one
portfolio. Each :meth:`~PortfolioStore.commit` is one transaction per session:

1. ``SELECT … FOR UPDATE`` on the portfolio's ``portfolio_state_current`` row (created with
   the first session), and a check that the committed log still ends exactly where the
   session's first event chains on (``last_seq``, ``last_hash``); anything else means a
   second writer, and the transaction is abandoned with :class:`ChainConflict`.
2. The session's ``trade_event`` rows, ``seq = last_seq + 1`` onwards, with
   ``prev_hash``/``hash``. A plain ``INSERT``: the A13 trigger refuses a repeated or
   skipped ``seq`` itself.
3. Rows derived from those events: ``order`` (inserted on ``ORDER_PLACED``, its ``status``
   moved on ``ORDER_FILLED``, ``ORDER_EXPIRED`` and a fill-time ``ORDER_REJECTED``),
   ``fill`` (one per ``ORDER_FILLED``) and the ``portfolio_value`` point of ``VALUED``.
   ``holding_history`` and the rebuild are left to A15.
4. ``portfolio_state_current``: ``last_seq``, ``last_hash``, ``last_session``, cash and
   the positions cache, ``{"<symbol>": {"quantity": <int>, "cost_basis": "<cents>"}}``.
5. Outbox rows (:func:`qs_template.messaging.add_event`) on topic
   ``quantsim.trading.portfolio``, keyed by portfolio id: ``fill.executed`` per fill,
   ``portfolio.updated`` per session and ``run.completed`` at the end. Event ids are
   derived from ``(portfolio_id, seq, event_type)``, so each is unique and stable.
"""

import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy import func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from qs_template import Database
from qs_template.events import EventEnvelope
from qs_template.messaging import add_event
from qs_trading.domain.events import (
    OrderExpiredV1,
    OrderFilledV1,
    OrderPlacedV1,
    OrderRejectedV1,
    RunCompletedV1,
    ValuedV1,
)
from qs_trading.domain.orders import OrderStatus
from qs_trading.engine.core import Engine, LoggedEvent, RunSpec, SessionResult
from qs_trading.engine.runner import ChainHead
from qs_trading.models import (
    fill,
    order,
    portfolio,
    portfolio_state_current,
    portfolio_value,
    strategy,
    trade_event,
)
from qs_trading.ports.market_environment import EnvironmentRef, FingerprintChanged

__all__ = ["ChainConflict", "PortfolioNotFound", "PortfolioStore", "load_spec", "outbox_event_id"]

PRODUCER = "trading"
AGGREGATE = "portfolio"
_OUTBOX_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "https://quantsim.local/trading/outbox")


class PortfolioNotFound(LookupError):
    """No portfolio has this id."""


class ChainConflict(RuntimeError):
    """The committed log does not end where the session being written chains on."""


def outbox_event_id(portfolio_id: uuid.UUID, seq: int, event_type: str) -> uuid.UUID:
    """The stable id of the outbox event published for the trade event at ``seq``."""
    return uuid.uuid5(_OUTBOX_NAMESPACE, f"{portfolio_id}:{seq}:{event_type}")


async def load_spec(session: AsyncSession, portfolio_id: uuid.UUID) -> RunSpec:
    """The run spec of a portfolio, from its row and its strategy's."""
    p, s = portfolio.c, strategy.c
    row = (
        await session.execute(
            select(
                p.initial_capital,
                p.cost_model,
                p.slippage_model,
                p.env_type,
                p.replay_environment_id,
                p.simulation_run_id,
                p.path_index,
                s.kind,
                s.params,
            )
            .join_from(portfolio, strategy, p.strategy_id == s.id)
            .where(p.id == portfolio_id)
        )
    ).first()
    if row is None:
        raise PortfolioNotFound(str(portfolio_id))
    if row.env_type == "replay":
        ref = EnvironmentRef("replay", str(row.replay_environment_id))
    else:
        ref = EnvironmentRef("simulation", str(row.simulation_run_id), row.path_index)
    return RunSpec(
        portfolio_id=portfolio_id,
        strategy_kind=row.kind,
        strategy_params=dict(row.params),
        initial_capital=row.initial_capital,
        cost_model=dict(row.cost_model),
        slippage_model=dict(row.slippage_model),
        environment=ref,
    )


def _positions_json(result: SessionResult) -> dict[str, Any]:
    return {
        symbol: {"quantity": position.quantity, "cost_basis": str(position.cost_basis)}
        for symbol, position in sorted(result.state.portfolio.positions.items())
    }


class PortfolioStore:
    """The trading_db sink of one portfolio's run. ``run_id`` (the job id) is added to
    the ``run.completed`` event when given."""

    def __init__(
        self, database: Database, portfolio_id: uuid.UUID, *, run_id: uuid.UUID | None = None
    ) -> None:
        self.database = database
        self.portfolio_id = portfolio_id
        self.run_id = run_id

    async def load_spec(self) -> RunSpec:
        async with self.database.transaction() as session:
            return await load_spec(session, self.portfolio_id)

    async def bind_fingerprint(self, fingerprint: str) -> None:
        async with self.database.transaction() as session:
            bound = (
                await session.execute(
                    select(portfolio.c.source_fingerprint)
                    .where(portfolio.c.id == self.portfolio_id)
                    .with_for_update()
                )
            ).first()
            if bound is None:
                raise PortfolioNotFound(str(self.portfolio_id))
            if bound.source_fingerprint is None:
                await session.execute(
                    update(portfolio)
                    .where(portfolio.c.id == self.portfolio_id)
                    .values(source_fingerprint=fingerprint, updated_at=func.now())
                )
            elif bound.source_fingerprint != fingerprint:
                raise FingerprintChanged(bound.source_fingerprint, fingerprint)

    async def head(self) -> ChainHead:
        async with self.database.transaction() as session:
            row = (
                await session.execute(
                    select(
                        portfolio_state_current.c.last_seq, portfolio_state_current.c.last_hash
                    ).where(portfolio_state_current.c.portfolio_id == self.portfolio_id)
                )
            ).first()
        if row is None:
            return ChainHead()
        return ChainHead(int(row.last_seq), row.last_hash)

    async def commit(self, engine: Engine, result: SessionResult) -> None:
        if not result.events:
            raise ValueError("a session always appends events")
        async with self.database.transaction() as session:
            await self._lock_head(session, engine, result.events[0])
            await session.execute(
                insert(trade_event),
                [
                    {
                        "portfolio_id": e.portfolio_id,
                        "seq": e.seq,
                        "event_time": e.event_time,
                        "type": e.type.value,
                        "version": e.version,
                        "payload": e.payload_json,
                        "prev_hash": e.prev_hash,
                        "hash": e.hash,
                    }
                    for e in result.events
                ],
            )
            for event in result.events:
                await self._project(session, event)
            state = result.state
            await session.execute(
                update(portfolio_state_current)
                .where(portfolio_state_current.c.portfolio_id == self.portfolio_id)
                .values(
                    last_seq=state.last_seq,
                    last_hash=state.last_hash,
                    last_session=result.session,
                    cash=state.portfolio.cash,
                    positions=_positions_json(result),
                    updated_at=func.now(),
                )
            )
            for event in result.events:
                await self._publish(session, event)

    async def _lock_head(self, session: AsyncSession, engine: Engine, first: LoggedEvent) -> None:
        psc = portfolio_state_current.c
        locked = (
            select(psc.last_seq, psc.last_hash)
            .where(psc.portfolio_id == self.portfolio_id)
            .with_for_update()
        )
        row = (await session.execute(locked)).first()
        if row is None:
            await session.execute(
                pg_insert(portfolio_state_current)
                .values(
                    portfolio_id=self.portfolio_id,
                    last_seq=0,
                    last_hash=None,
                    cash=engine.initial_state().portfolio.cash,
                )
                .on_conflict_do_nothing(index_elements=[psc.portfolio_id])
            )
            row = (await session.execute(locked)).one()
        if (int(row.last_seq), row.last_hash) != (first.seq - 1, first.prev_hash):
            raise ChainConflict(
                f"portfolio {self.portfolio_id} log ends at seq {row.last_seq}; this session"
                f" chains onto seq {first.seq - 1}"
            )

    async def _set_status(self, session: AsyncSession, order_id: str, status: OrderStatus) -> None:
        await session.execute(
            update(order)
            .where(order.c.portfolio_id == self.portfolio_id, order.c.order_id == order_id)
            .values(status=status.value, updated_at=func.now())
        )

    async def _project(self, session: AsyncSession, event: LoggedEvent) -> None:
        payload = event.payload
        if isinstance(payload, OrderPlacedV1):
            await session.execute(
                insert(order).values(
                    portfolio_id=self.portfolio_id,
                    order_id=payload.order_id,
                    symbol=payload.symbol,
                    side=payload.side.value,
                    quantity=payload.quantity,
                    order_type=payload.order_type.value,
                    limit_price=payload.limit_price,
                    placed_seq=event.seq,
                    placed_session=payload.session,
                    expires_session=payload.expires_session,
                    status=OrderStatus.OPEN.value,
                )
            )
        elif isinstance(payload, OrderFilledV1):
            await session.execute(
                insert(fill).values(
                    portfolio_id=self.portfolio_id,
                    seq=event.seq,
                    order_id=payload.order_id,
                    session=payload.session,
                    symbol=payload.symbol,
                    side=payload.side.value,
                    quantity=payload.quantity,
                    reference_price=payload.reference_price,
                    fill_price=payload.fill_price,
                    slippage=payload.slippage,
                    cost_fixed=payload.cost_fixed,
                    cost_per_share=payload.cost_per_share,
                    cost_percentage=payload.cost_percentage,
                    cost_total=payload.cost_total,
                    cash_after=payload.cash_after,
                )
            )
            await self._set_status(session, payload.order_id, OrderStatus.FILLED)
        elif isinstance(payload, OrderExpiredV1):
            await self._set_status(session, payload.order_id, OrderStatus.EXPIRED)
        elif isinstance(payload, OrderRejectedV1) and payload.order_id is not None:
            await self._set_status(session, payload.order_id, OrderStatus.REJECTED)
        elif isinstance(payload, ValuedV1):
            await session.execute(
                insert(portfolio_value).values(
                    portfolio_id=self.portfolio_id,
                    ts=payload.ts,
                    session=payload.session,
                    seq=event.seq,
                    cash=payload.cash,
                    market_value=payload.market_value,
                    value=payload.portfolio_value,
                    realised_pnl=payload.realised_pnl,
                    unrealised_pnl=payload.unrealised_pnl,
                    total_costs=payload.total_costs,
                )
            )

    def _envelope(
        self, event: LoggedEvent, event_type: str, data: Mapping[str, Any]
    ) -> EventEnvelope:
        return EventEnvelope(
            event_id=outbox_event_id(self.portfolio_id, event.seq, event_type),
            event_type=event_type,
            producer=PRODUCER,
            aggregate_type=AGGREGATE,
            aggregate_id=str(self.portfolio_id),
            data={"portfolio_id": str(self.portfolio_id), "seq": event.seq, **data},
        )

    async def _publish(self, session: AsyncSession, event: LoggedEvent) -> None:
        payload = event.payload
        envelope: EventEnvelope | None = None
        if isinstance(payload, OrderFilledV1):
            envelope = self._envelope(event, "fill.executed", event.payload_json)
        elif isinstance(payload, ValuedV1):
            envelope = self._envelope(
                event, "portfolio.updated", {**event.payload_json, "hash": event.hash}
            )
        elif isinstance(payload, RunCompletedV1):
            data: dict[str, Any] = {**event.payload_json, "final_hash": event.hash}
            if self.run_id is not None:
                data["run_id"] = str(self.run_id)
            envelope = self._envelope(event, "run.completed", data)
        if envelope is not None:
            await add_event(session, envelope)
