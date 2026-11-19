"""Data access behind the Trading API (task A16).

The routes talk to a :class:`TradingStore` made per request from the request's session,
so they can be exercised without a database by handing :func:`build_routers` another
store. :class:`SqlTradingStore` is the trading_db implementation; it never commits, the
request's transaction does.
"""

import uuid
from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import Any, Protocol

from sqlalchemy import exists, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

from qs_template.jobs import JobQueue
from qs_trading.jobs import ENGINE_RUN, submit_engine_run
from qs_trading.models import job, portfolio, strategy, trade_event
from qs_trading.schemas import (
    EventOut,
    PortfolioOut,
    RunAccepted,
    RunOut,
    StrategyOut,
    money_text,
)

__all__ = [
    "PortfolioValues",
    "SqlTradingStore",
    "StoreDependency",
    "StoreFactory",
    "TradingStore",
    "sql_store",
]

PortfolioValues = dict[str, Any]
"""The columns of a new portfolio row: name, strategy_id, initial_capital (Decimal),
cost_model, slippage_model (stored JSON), env_type, replay_environment_id,
simulation_run_id, path_index."""


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

    async def submit_run(
        self, portfolio_id: uuid.UUID, idempotency_key: str | None
    ) -> RunAccepted: ...

    async def get_run(self, portfolio_id: uuid.UUID, job_id: uuid.UUID) -> RunOut | None:
        """The ``engine.run`` job ``job_id`` of this portfolio, or ``None``."""
        ...

    async def events(self, portfolio_id: uuid.UUID, after_seq: int, limit: int) -> list[EventOut]:
        """Up to ``limit`` log events with ``seq > after_seq``, ascending."""
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
        cost_model=dict(row.cost_model),
        slippage_model=dict(row.slippage_model),
        env_type=row.env_type,
        replay_environment_id=row.replay_environment_id,
        simulation_run_id=row.simulation_run_id,
        path_index=row.path_index,
        source_fingerprint=row.source_fingerprint,
        created_at=row.created_at,
        updated_at=row.updated_at,
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


def sql_store(queue: JobQueue) -> StoreFactory:
    """The trading_db store factory, submitting runs to ``queue``."""

    def make(session: AsyncSession) -> TradingStore:
        return SqlTradingStore(session, queue)

    return make
