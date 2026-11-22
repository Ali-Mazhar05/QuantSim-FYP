"""Data access behind the Trading API (task A16).

The routes talk to a :class:`TradingStore` made per request from the request's session,
so they can be exercised without a database by handing :func:`build_routers` another
store. :class:`SqlTradingStore` is the trading_db implementation; it never commits, the
request's transaction does.

The projection reads (A16 part 2) share their row-to-response conversions with any other
store: :func:`fill_out`, :func:`value_out`, :func:`holding_change_out` and
:func:`holdings_out` take a row as :mod:`qs_trading.projections.fold` yields it (column
name to value), so the fold's rows and the stored rows give the same responses.

**One active run per portfolio.** :meth:`TradingStore.submit_run` refuses a new run job
(:class:`RunInProgress`) while another ``engine.run`` job of the portfolio is queued or
running; the same idempotency key still returns its job. The SQL store makes this race
safe by locking the portfolio row (``SELECT ... FOR UPDATE``) before it looks: two
submits for one portfolio take turns, and the second sees the first's job once the first
commits. Submits for different portfolios never wait for each other.
"""

import uuid
from collections.abc import Awaitable, Callable, Mapping
from decimal import Decimal
from typing import Any, Protocol

from sqlalchemy import and_, exists, insert, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

from qs_template.jobs import JobQueue
from qs_trading.jobs import ENGINE_RUN, engine_run_key, submit_engine_run
from qs_trading.metrics import RunFigures
from qs_trading.models import (
    fill,
    holding_history,
    job,
    portfolio,
    portfolio_state_current,
    portfolio_value,
    strategy,
    trade_event,
)
from qs_trading.projections.figures import load_run_figures
from qs_trading.projections.fold import PortfolioSnapshot, positions_json
from qs_trading.projections.rebuild import (
    RebuildResult,
    rebuild_portfolio,
    state_as_of,
    verify_portfolio,
)
from qs_trading.projections.verify import ChainReport
from qs_trading.schemas import (
    ChainReportOut,
    CostModelOut,
    EventOut,
    FillOut,
    HoldingChangeOut,
    HoldingsOut,
    PortfolioOut,
    PositionOut,
    RebuildOut,
    RunAccepted,
    RunOut,
    SlippageModelOut,
    StateOut,
    StrategyOut,
    TableDifferenceOut,
    ValuePointOut,
    money_text,
)

__all__ = [
    "ACTIVE_JOB_STATUSES",
    "PortfolioValues",
    "RunInProgress",
    "SqlTradingStore",
    "StoreDependency",
    "StoreFactory",
    "TradingStore",
    "chain_report_out",
    "fill_out",
    "holding_change_out",
    "holdings_out",
    "rebuild_out",
    "sql_store",
    "state_out",
    "value_out",
]

PortfolioValues = dict[str, Any]
"""The columns of a new portfolio row: name, strategy_id, initial_capital (Decimal),
cost_model, slippage_model (stored JSON), env_type, replay_environment_id,
simulation_run_id, path_index."""


ACTIVE_JOB_STATUSES = ("queued", "running")
"""A run job in one of these states blocks a new run of its portfolio."""


class RunInProgress(Exception):
    """The portfolio already has a queued or running run job, ``job_id``."""

    def __init__(self, portfolio_id: uuid.UUID, job_id: uuid.UUID) -> None:
        super().__init__(f"portfolio {portfolio_id} already has run {job_id} in progress")
        self.portfolio_id = portfolio_id
        self.job_id = job_id


class TradingStore(Protocol):
    async def list_strategies(self) -> list[StrategyOut]: ...

    async def get_strategy(self, strategy_id: uuid.UUID) -> StrategyOut | None: ...

    async def create_strategy(
        self, *, name: str, kind: str, params: dict[str, Any], owner_id: uuid.UUID
    ) -> StrategyOut: ...

    async def replace_strategy(
        self, strategy_id: uuid.UUID, *, name: str, kind: str, params: dict[str, Any]
    ) -> StrategyOut | None: ...

    async def strategy_has_run(self, strategy_id: uuid.UUID) -> bool:
        """Whether a portfolio on this strategy has written its log already."""
        ...

    async def list_portfolios(self) -> list[PortfolioOut]: ...

    async def get_portfolio(self, portfolio_id: uuid.UUID) -> PortfolioOut | None: ...

    async def create_portfolio(
        self, values: PortfolioValues, *, owner_id: uuid.UUID
    ) -> PortfolioOut: ...

    async def submit_run(self, portfolio_id: uuid.UUID, idempotency_key: str | None) -> RunAccepted:
        """Queues a run, or returns the job of the same idempotency key. Raises
        :class:`RunInProgress` when the key is new and another run job of the portfolio
        is still queued or running."""
        ...

    async def get_run(self, portfolio_id: uuid.UUID, job_id: uuid.UUID) -> RunOut | None:
        """The ``engine.run`` job ``job_id`` of this portfolio, or ``None``."""
        ...

    async def events(self, portfolio_id: uuid.UUID, after_seq: int, limit: int) -> list[EventOut]:
        """Up to ``limit`` log events with ``seq > after_seq``, ascending."""
        ...

    async def fills(self, portfolio_id: uuid.UUID, after_seq: int, limit: int) -> list[FillOut]:
        """Up to ``limit`` fills with ``seq > after_seq``, ascending."""
        ...

    async def holdings(self, portfolio_id: uuid.UUID) -> HoldingsOut:
        """The current positions and cash; empty before the first run."""
        ...

    async def holding_history(
        self, portfolio_id: uuid.UUID, after_seq: int, limit: int
    ) -> list[HoldingChangeOut]:
        """Up to ``limit`` holding changes with ``seq > after_seq``, ascending."""
        ...

    async def value_series(self, portfolio_id: uuid.UUID) -> list[ValuePointOut]:
        """Every valuation, ascending by session."""
        ...

    async def state_as_of(self, portfolio_id: uuid.UUID, seq: int | None) -> StateOut:
        """The state right after the event at ``seq`` (the last event when ``None``).
        Raises ``LookupError`` when there is no such event, and
        :class:`~qs_trading.projections.rebuild.ChainBroken` or
        :class:`~qs_trading.projections.fold.ProjectionError` for a broken log."""
        ...

    async def rebuild(self, portfolio_id: uuid.UUID, *, apply: bool) -> RebuildOut:
        """Rebuilds the projections from the log and compares them with the stored ones
        (:func:`~qs_trading.projections.rebuild.rebuild_portfolio`); raises as
        :meth:`state_as_of` does for a broken log."""
        ...

    async def verify(self, portfolio_id: uuid.UUID) -> ChainReportOut:
        """The hash-chain report of the log."""
        ...

    async def run_figures(self, portfolio_id: uuid.UUID) -> RunFigures:
        """What the portfolio's metrics are computed from."""
        ...


StoreFactory = Callable[[AsyncSession], TradingStore]

StoreDependency = Callable[..., Awaitable[TradingStore]]
"""The FastAPI dependency that hands a route the request's store."""


def _strategy_out(row: Any) -> StrategyOut:
    return StrategyOut(
        id=row.id,
        name=row.name,
        kind=row.kind,
        params=dict(row.params),
        owner_id=row.owner_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _portfolio_out(row: Any) -> PortfolioOut:
    capital: Decimal = row.initial_capital
    return PortfolioOut(
        id=row.id,
        name=row.name,
        strategy_id=row.strategy_id,
        strategy_name=row.strategy_name,
        strategy_kind=row.strategy_kind,
        owner_id=row.owner_id,
        initial_capital=money_text(capital),
        base_currency=row.base_currency,
        cost_model=CostModelOut.model_validate(row.cost_model),
        slippage_model=SlippageModelOut.model_validate(row.slippage_model),
        env_type=row.env_type,
        replay_environment_id=row.replay_environment_id,
        simulation_run_id=row.simulation_run_id,
        path_index=row.path_index,
        source_fingerprint=row.source_fingerprint,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


_MONEY_FILL_COLUMNS = (
    "reference_price",
    "fill_price",
    "slippage",
    "cost_fixed",
    "cost_per_share",
    "cost_percentage",
    "cost_total",
    "cash_after",
)
_MONEY_VALUE_COLUMNS = (
    "cash",
    "market_value",
    "value",
    "realised_pnl",
    "unrealised_pnl",
    "total_costs",
)


def _positions(positions: Mapping[str, Any]) -> list[PositionOut]:
    """Open positions from the ``{"<symbol>": {"quantity", "cost_basis"}}`` cache."""
    return [
        PositionOut(
            symbol=symbol,
            quantity=int(item["quantity"]),
            cost_basis=money_text(Decimal(str(item["cost_basis"]))),
        )
        for symbol, item in sorted(positions.items())
    ]


def fill_out(row: Mapping[str, Any]) -> FillOut:
    """A ``fill`` row as served."""
    money = {name: money_text(row[name]) for name in _MONEY_FILL_COLUMNS}
    return FillOut(
        seq=row["seq"],
        order_id=row["order_id"],
        session=row["session"],
        symbol=row["symbol"],
        side=row["side"],
        quantity=row["quantity"],
        **money,
    )


def holding_change_out(row: Mapping[str, Any]) -> HoldingChangeOut:
    """A ``holding_history`` row as served."""
    return HoldingChangeOut(
        seq=row["seq"],
        session=row["session"],
        symbol=row["symbol"],
        quantity=row["quantity"],
        cost_basis=money_text(row["cost_basis"]),
    )


def value_out(row: Mapping[str, Any]) -> ValuePointOut:
    """A ``portfolio_value`` row as served."""
    money = {name: money_text(row[name]) for name in _MONEY_VALUE_COLUMNS}
    return ValuePointOut(session=row["session"], ts=row["ts"], seq=row["seq"], **money)


def holdings_out(portfolio_id: uuid.UUID, state: Mapping[str, Any] | None) -> HoldingsOut:
    """The ``portfolio_state_current`` row as served; ``None`` before the first run."""
    if state is None:
        return HoldingsOut(
            portfolio_id=portfolio_id, last_seq=0, last_session=None, cash=None, positions=[]
        )
    return HoldingsOut(
        portfolio_id=portfolio_id,
        last_seq=state["last_seq"],
        last_session=state["last_session"],
        cash=money_text(state["cash"]),
        positions=_positions(state["positions"] or {}),
    )


def state_out(snapshot: PortfolioSnapshot) -> StateOut:
    last_value = snapshot.last_value
    return StateOut(
        portfolio_id=snapshot.portfolio_id,
        seq=snapshot.seq,
        hash=snapshot.hash,
        session=snapshot.session,
        initial_capital=money_text(snapshot.initial_capital),
        cash=money_text(snapshot.cash),
        positions=_positions(positions_json(snapshot.positions)),
        realised_pnl=money_text(snapshot.realised_pnl),
        total_costs=money_text(snapshot.total_costs),
        open_orders=list(snapshot.open_orders),
        last_value=None if last_value is None else money_text(last_value),
        last_valued_seq=snapshot.last_valued_seq,
    )


def rebuild_out(result: RebuildResult) -> RebuildOut:
    return RebuildOut(
        portfolio_id=result.portfolio_id,
        status=result.status,
        events=result.events,
        final_seq=result.final_seq,
        final_hash=result.final_hash,
        differences=[
            TableDifferenceOut(
                table=d.table,
                missing=list(d.missing),
                unexpected=list(d.unexpected),
                changed=list(d.changed),
            )
            for d in result.differences
        ],
        applied=result.applied,
    )


def chain_report_out(report: ChainReport) -> ChainReportOut:
    return ChainReportOut(
        portfolio_id=report.portfolio_id,
        valid=report.valid,
        events=report.events,
        last_seq=report.last_seq,
        last_hash=report.last_hash,
        broken_seq=report.broken_seq,
        reason=report.reason,
    )


_PORTFOLIO_COLUMNS = (
    *portfolio.c,
    strategy.c.name.label("strategy_name"),
    strategy.c.kind.label("strategy_kind"),
)


class SqlTradingStore:
    def __init__(self, session: AsyncSession, queue: JobQueue) -> None:
        self.session = session
        self.queue = queue

    async def list_strategies(self) -> list[StrategyOut]:
        rows = await self.session.execute(
            select(strategy).order_by(strategy.c.created_at.desc(), strategy.c.id)
        )
        return [_strategy_out(row) for row in rows]

    async def get_strategy(self, strategy_id: uuid.UUID) -> StrategyOut | None:
        row = (
            await self.session.execute(select(strategy).where(strategy.c.id == strategy_id))
        ).first()
        return None if row is None else _strategy_out(row)

    async def create_strategy(
        self, *, name: str, kind: str, params: dict[str, Any], owner_id: uuid.UUID
    ) -> StrategyOut:
        row = (
            await self.session.execute(
                insert(strategy)
                .values(name=name, kind=kind, params=params, owner_id=owner_id)
                .returning(*strategy.c)
            )
        ).one()
        return _strategy_out(row)

    async def replace_strategy(
        self, strategy_id: uuid.UUID, *, name: str, kind: str, params: dict[str, Any]
    ) -> StrategyOut | None:
        row = (
            await self.session.execute(
                update(strategy)
                .where(strategy.c.id == strategy_id)
                .values(name=name, kind=kind, params=params, updated_at=func.now())
                .returning(*strategy.c)
            )
        ).first()
        return None if row is None else _strategy_out(row)

    async def strategy_has_run(self, strategy_id: uuid.UUID) -> bool:
        logged = (
            select(trade_event.c.seq)
            .join(portfolio, portfolio.c.id == trade_event.c.portfolio_id)
            .where(portfolio.c.strategy_id == strategy_id)
        )
        return bool(await self.session.scalar(select(exists(logged))))

    def _portfolios(self) -> Any:
        return select(*_PORTFOLIO_COLUMNS).join_from(
            portfolio, strategy, portfolio.c.strategy_id == strategy.c.id
        )

    async def list_portfolios(self) -> list[PortfolioOut]:
        rows = await self.session.execute(
            self._portfolios().order_by(portfolio.c.created_at.desc(), portfolio.c.id)
        )
        return [_portfolio_out(row) for row in rows]

    async def get_portfolio(self, portfolio_id: uuid.UUID) -> PortfolioOut | None:
        row = (
            await self.session.execute(self._portfolios().where(portfolio.c.id == portfolio_id))
        ).first()
        return None if row is None else _portfolio_out(row)

    async def create_portfolio(
        self, values: PortfolioValues, *, owner_id: uuid.UUID
    ) -> PortfolioOut:
        new_id = (
            await self.session.execute(
                insert(portfolio).values(**values, owner_id=owner_id).returning(portfolio.c.id)
            )
        ).scalar_one()
        created = await self.get_portfolio(new_id)
        assert created is not None
        return created

    async def submit_run(self, portfolio_id: uuid.UUID, idempotency_key: str | None) -> RunAccepted:
        # Serialises the submits of this portfolio until the request's transaction ends
        await self.session.execute(
            select(portfolio.c.id).where(portfolio.c.id == portfolio_id).with_for_update()
        )
        repeated = await self.session.scalar(
            select(job.c.id).where(
                job.c.idempotency_key == engine_run_key(portfolio_id, idempotency_key)
            )
        )
        if repeated is None:
            active = await self.active_run(portfolio_id)
            if active is not None:
                raise RunInProgress(portfolio_id, active)
        submitted = await submit_engine_run(
            self.session, self.queue, portfolio_id, idempotency_key=idempotency_key
        )
        state = await self.queue.get(self.session, submitted.id)
        assert state is not None
        return RunAccepted(
            job_id=submitted.id,
            portfolio_id=portfolio_id,
            status=state.status,
            created=submitted.created,
        )

    async def active_run(self, portfolio_id: uuid.UUID) -> uuid.UUID | None:
        """The oldest queued or running run job of the portfolio. A running job whose
        lease ran out on its last allowed attempt only waits for a worker to mark it
        failed, so it no longer counts."""
        t = job.c
        now = func.now()
        live = or_(
            t.lease_expires_at.is_(None), t.lease_expires_at >= now, t.attempts < t.max_attempts
        )
        found: uuid.UUID | None = await self.session.scalar(
            select(t.id)
            .where(
                t.kind == ENGINE_RUN,
                t.payload["portfolio_id"].astext == str(portfolio_id),
                or_(t.status == "queued", and_(t.status == "running", live)),
            )
            .order_by(t.created_at, t.id)
            .limit(1)
        )
        return found

    async def get_run(self, portfolio_id: uuid.UUID, job_id: uuid.UUID) -> RunOut | None:
        row = (
            await self.session.execute(
                select(job).where(
                    job.c.id == job_id,
                    job.c.kind == ENGINE_RUN,
                    job.c.payload["portfolio_id"].astext == str(portfolio_id),
                )
            )
        ).first()
        if row is None:
            return None
        return RunOut(
            job_id=row.id,
            portfolio_id=portfolio_id,
            status=row.status,
            progress=row.progress,
            attempts=row.attempts,
            max_attempts=row.max_attempts,
            error=row.error,
            result=row.result,
            created_at=row.created_at,
            started_at=row.started_at,
            finished_at=row.finished_at,
        )

    async def events(self, portfolio_id: uuid.UUID, after_seq: int, limit: int) -> list[EventOut]:
        e = trade_event.c
        rows = await self.session.execute(
            select(e.seq, e.type, e.version, e.event_time, e.payload, e.prev_hash, e.hash)
            .where(e.portfolio_id == portfolio_id, e.seq > after_seq)
            .order_by(e.seq)
            .limit(limit)
        )
        return [
            EventOut(
                seq=row.seq,
                type=row.type,
                version=row.version,
                event_time=row.event_time,
                payload=dict(row.payload),
                prev_hash=row.prev_hash,
                hash=row.hash,
            )
            for row in rows
        ]

    async def fills(self, portfolio_id: uuid.UUID, after_seq: int, limit: int) -> list[FillOut]:
        rows = await self.session.execute(
            select(fill)
            .where(fill.c.portfolio_id == portfolio_id, fill.c.seq > after_seq)
            .order_by(fill.c.seq)
            .limit(limit)
        )
        return [fill_out(dict(row._mapping)) for row in rows]

    async def _state_row(self, portfolio_id: uuid.UUID) -> Mapping[str, Any] | None:
        row = (
            await self.session.execute(
                select(portfolio_state_current).where(
                    portfolio_state_current.c.portfolio_id == portfolio_id
                )
            )
        ).first()
        return None if row is None else dict(row._mapping)

    async def holdings(self, portfolio_id: uuid.UUID) -> HoldingsOut:
        return holdings_out(portfolio_id, await self._state_row(portfolio_id))

    async def holding_history(
        self, portfolio_id: uuid.UUID, after_seq: int, limit: int
    ) -> list[HoldingChangeOut]:
        h = holding_history.c
        rows = await self.session.execute(
            select(holding_history)
            .where(h.portfolio_id == portfolio_id, h.seq > after_seq)
            .order_by(h.seq, h.symbol)
            .limit(limit)
        )
        return [holding_change_out(dict(row._mapping)) for row in rows]

    def _values(self, portfolio_id: uuid.UUID, *columns: Any) -> Any:
        v = portfolio_value.c
        return select(*columns).where(v.portfolio_id == portfolio_id).order_by(v.session, v.seq)

    async def value_series(self, portfolio_id: uuid.UUID) -> list[ValuePointOut]:
        rows = await self.session.execute(self._values(portfolio_id, portfolio_value))
        return [value_out(dict(row._mapping)) for row in rows]

    async def state_as_of(self, portfolio_id: uuid.UUID, seq: int | None) -> StateOut:
        if seq is None:
            seq = await self.session.scalar(
                select(func.max(trade_event.c.seq)).where(
                    trade_event.c.portfolio_id == portfolio_id
                )
            )
            if seq is None:
                raise LookupError(f"portfolio {portfolio_id} has no events")
        return state_out(await state_as_of(self.session, portfolio_id, seq))

    async def rebuild(self, portfolio_id: uuid.UUID, *, apply: bool) -> RebuildOut:
        return rebuild_out(await rebuild_portfolio(self.session, portfolio_id, apply=apply))

    async def verify(self, portfolio_id: uuid.UUID) -> ChainReportOut:
        return chain_report_out(await verify_portfolio(self.session, portfolio_id))

    async def run_figures(self, portfolio_id: uuid.UUID) -> RunFigures:
        return await load_run_figures(self.session, portfolio_id)


def sql_store(queue: JobQueue) -> StoreFactory:
    """The trading_db store factory, submitting runs to ``queue``."""

    def make(session: AsyncSession) -> TradingStore:
        return SqlTradingStore(session, queue)

    return make
