"""Background job handlers of the Trading service, by job kind.

A handler receives the claimed job and a progress reporter and returns a JSON-able result
(or ``None``). :func:`build_handlers` gives the handlers the worker runs; the API submits
jobs of the same kinds through :func:`job_queue`.

``engine.run`` (task A14) runs one portfolio over its market environment: payload
``{"portfolio_id": "<uuid>"}``, progress = sessions committed / sessions in the
environment, reported (and the lease extended) after every session. A retried or
reclaimed job resumes from the committed log (A-FR-13). The result is the run's final
``seq``, hash and value.
"""

import uuid
from collections.abc import Callable

from sqlalchemy.ext.asyncio import AsyncSession

from qs_template import Database
from qs_template.jobs import Handler, Job, JobQueue, ProgressReporter, Submitted
from qs_trading.engine.runner import run_portfolio
from qs_trading.engine.store import PortfolioStore
from qs_trading.models import job
from qs_trading.ports.market_environment import (
    EnvironmentRef,
    MarketEnvironment,
    MarketEnvironmentError,
)
from qs_trading.settings import TradingSettings

__all__ = [
    "ENGINE_RUN",
    "EnvironmentFactory",
    "build_handlers",
    "engine_run_handler",
    "engine_run_key",
    "job_queue",
    "no_environments",
    "submit_engine_run",
]

ENGINE_RUN = "engine.run"

EnvironmentFactory = Callable[[EnvironmentRef], MarketEnvironment]
"""Opens the market environment a portfolio is bound to."""


def no_environments(ref: EnvironmentRef) -> MarketEnvironment:
    """The factory until the HTTP adapters (A17) are wired: every run fails clearly."""
    raise MarketEnvironmentError(f"no market adapter is configured for {ref.env_type} {ref.env_id}")


def job_queue(settings: TradingSettings) -> JobQueue:
    return JobQueue(
        job, lease_seconds=settings.job_lease_seconds, max_attempts=settings.job_max_attempts
    )


def engine_run_key(portfolio_id: uuid.UUID, idempotency_key: str | None = None) -> str:
    """The job idempotency key of a portfolio's run. Without a client key a portfolio has
    one run job, which is what its single append-only log allows."""
    base = f"{ENGINE_RUN}:{portfolio_id}"
    return base if idempotency_key is None else f"{base}:{idempotency_key}"


async def submit_engine_run(
    session: AsyncSession,
    queue: JobQueue,
    portfolio_id: uuid.UUID,
    *,
    idempotency_key: str | None = None,
) -> Submitted:
    """Queue the run of ``portfolio_id``, or return the job already queued for it."""
    return await queue.submit(
        session,
        ENGINE_RUN,
        {"portfolio_id": str(portfolio_id)},
        idempotency_key=engine_run_key(portfolio_id, idempotency_key),
    )


def engine_run_handler(database: Database, environments: EnvironmentFactory) -> Handler:
    async def handle(claimed: Job, report: ProgressReporter) -> dict[str, object]:
        portfolio_id = uuid.UUID(str(claimed.payload["portfolio_id"]))
        store = PortfolioStore(database, portfolio_id, run_id=claimed.id)
        spec = await store.load_spec()
        result = await run_portfolio(spec, environments(spec.environment), store, progress=report)
        return result.to_json()

    return handle


def build_handlers(
    database: Database, environments: EnvironmentFactory = no_environments
) -> dict[str, Handler]:
    """Every handler of the service, by job kind."""
    return {ENGINE_RUN: engine_run_handler(database, environments)}
