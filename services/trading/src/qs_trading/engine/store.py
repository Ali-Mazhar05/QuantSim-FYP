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
3. The projection rows of those events, folded onto the locked state row by
   :func:`qs_trading.projections.fold.fold` and written with
   :func:`qs_trading.projections.persist.write_rows` (A15): ``order`` (inserted on
   ``ORDER_PLACED``, its ``status`` moved on ``ORDER_FILLED``, ``ORDER_EXPIRED`` and a
   fill-time ``ORDER_REJECTED``), ``fill`` and ``holding_history`` (one each per
   ``ORDER_FILLED``) and the ``portfolio_value`` point of ``VALUED``. The rebuild folds the
   whole log with the same function, so live and rebuilt rows cannot drift apart; the
   folded books must also equal the engine's, or the session is not committed.
4. ``portfolio_state_current``: ``last_seq``, ``last_hash``, ``last_session``, cash and
   the positions cache, ``{"<symbol>": {"quantity": <int>, "cost_basis": "<cents>"}}``,
   as the fold's :meth:`~qs_trading.projections.fold.Ledger.state_row`.
5. On the session that completes a run started by a job (``run_id`` given): the run's
   ``portfolio_metrics`` row (A16), computed with the shared metrics library (K6) from
   the projections just written, so it always matches the committed log.
6. Outbox rows (:func:`qs_template.messaging.add_event`) on topic
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
from qs_trading.domain.events import OrderFilledV1, RunCompletedV1, ValuedV1
from qs_trading.engine.core import Engine, LoggedEvent, RunSpec, SessionResult
from qs_trading.engine.runner import ChainHead
from qs_trading.metrics import QUANT_METRICS, MetricsCalculator
from qs_trading.models import (
    portfolio,
    portfolio_metrics,
    portfolio_state_current,
    strategy,
    trade_event,
)
from qs_trading.ports.market_environment import EnvironmentRef, FingerprintChanged
from qs_trading.projections.figures import load_run_figures
from qs_trading.projections.fold import (
    Ledger,
    ProjectedEvent,
    ProjectionError,
    ProjectionRows,
    fold,
)
from qs_trading.projections.persist import write_rows

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


def _folded(head: Ledger, result: SessionResult) -> tuple[Ledger, ProjectionRows]:
    """The session's events folded onto the committed head; the folded books must be the
    engine's."""
    ledger, rows = fold(
        head,
        (ProjectedEvent(e.seq, e.prev_hash, e.hash, e.payload) for e in result.events),
    )
    state = result.state
    books = ledger.books
    if (
        books is None
        or (ledger.last_seq, ledger.last_hash, ledger.last_session)
        != (state.last_seq, state.last_hash, result.session)
        or books.cash != state.portfolio.cash
        or dict(books.positions) != dict(state.portfolio.positions)
    ):
        raise ProjectionError(state.last_seq, "the folded books differ from the engine's")
    return ledger, rows


class PortfolioStore:
    """The trading_db sink of one portfolio's run. With a ``run_id`` (the job id), the
    ``run.completed`` event carries it and the session that completes the run also stores
    the run's ``portfolio_metrics`` row, computed by ``metrics`` (A16, A-FR-14)."""

    def __init__(
        self,
        database: Database,
        portfolio_id: uuid.UUID,
        *,
        run_id: uuid.UUID | None = None,
        metrics: MetricsCalculator = QUANT_METRICS,
    ) -> None:
        self.database = database
        self.portfolio_id = portfolio_id
        self.run_id = run_id
        self.metrics = metrics

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
            head = await self._lock_head(session, engine, result.events[0])
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
            ledger, rows = _folded(head, result)
            await write_rows(session, self.portfolio_id, rows)
            state_row = ledger.state_row()
            if state_row is None:
                raise ProjectionError(result.state.last_seq, "a committed session has a state")
            del state_row["portfolio_id"]
            await session.execute(
                update(portfolio_state_current)
                .where(portfolio_state_current.c.portfolio_id == self.portfolio_id)
                .values(**state_row, updated_at=func.now())
            )
            if self.run_id is not None and any(
                isinstance(e.payload, RunCompletedV1) for e in result.events
            ):
                await self._store_metrics(session, self.run_id)
            for event in result.events:
                await self._publish(session, event)

    async def _store_metrics(self, session: AsyncSession, run_id: uuid.UUID) -> None:
        """The completed run's metrics, in the transaction that commits its last session,
        so a stored row always matches the committed log. A repeat is a no-op."""
        figures = await load_run_figures(session, self.portfolio_id)
        final_value = figures.final_value
        if figures.final_hash is None or final_value is None:
            raise ProjectionError(figures.final_seq, "a completed run has a head and a value")
        series = self.metrics.series_metrics(figures)
        await session.execute(
            pg_insert(portfolio_metrics)
            .values(
                run_id=run_id,
                portfolio_id=self.portfolio_id,
                final_seq=figures.final_seq,
                final_hash=figures.final_hash,
                sessions=figures.sessions,
                final_value=final_value,
                total_return=series.total_return,
                volatility=series.volatility,
                sharpe=series.sharpe,
                max_drawdown=series.max_drawdown,
                turnover=series.turnover,
                trades=figures.trades,
                total_costs=figures.total_costs,
            )
            .on_conflict_do_nothing(index_elements=[portfolio_metrics.c.run_id])
        )

    async def _lock_head(self, session: AsyncSession, engine: Engine, first: LoggedEvent) -> Ledger:
        psc = portfolio_state_current.c
        locked = (
            select(psc.last_seq, psc.last_hash, psc.last_session, psc.cash, psc.positions)
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
        return Ledger.from_state_row(self.portfolio_id, dict(row._mapping))

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
