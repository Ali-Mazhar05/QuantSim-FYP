"""Background job handlers of the Trading service, by job kind.

A handler receives the claimed job and a progress reporter and returns a JSON-able result
(or ``None``). :func:`build_handlers` gives the handlers the worker runs; the API submits
jobs of the same kinds through :func:`job_queue`.

``engine.run`` (task A14) runs one portfolio over its market environment: payload
``{"portfolio_id": "<uuid>"}``, progress = sessions committed / sessions in the
environment, reported (and the lease extended) after every session. A retried or
reclaimed job resumes from the committed log (A-FR-13). The result is the run's final
``seq``, hash and value.

Which market environments a run can open comes from :func:`environment_factory`: a
replay over the market service's feed when ``QS_TRADING_MARKET_URL`` is set, a simulation
path over the simulation service's feed when ``QS_TRADING_SIMULATION_URL`` is set (the
HTTP adapters, A17); otherwise, on LOCAL and DEV with ``QS_TRADING_DEMO_ENVIRONMENTS`` set,
the fixture files of a directory, or none.

**Permanent and transient failures.** The K1 worker queues a job whose handler raised
again while attempts remain. That suits a lost database connection or a timeout, but a
run that failed because of what it runs on fails the same way every time, so the handler
records those failures as final itself, with K1's own ``JobQueue.fail(..., retry=False)``:
:data:`PERMANENT_ERRORS` lists them (no portfolio, the engine refusing the spec or the
ticks, a resume that does not reproduce the log, a source fingerprint that changed, a
fixture that is missing or invalid, no market adapter, a log that does not fold, a feed
that refuses the environment or breaks the contract). The
fail is fenced by the claim: it only applies while the job is still ``running`` on the
attempt this handler was given, under the lease owner that holds it, so a worker that
already lost the job cannot end it. The handler then returns, and the worker's own
``complete`` finds the job no longer running and leaves it failed.

Everything else is transient and retried up to ``max_attempts``: database and connection
errors, timeouts, a feed that is down for now
(:class:`~qs_trading.adapters.feed_client.FeedUnavailable`), and
:class:`~qs_trading.engine.store.ChainConflict`. A chain conflict means another writer
appended to the log first (a reclaimed job whose old worker was still running); a retry
resumes from the committed log (A-FR-13) and either continues or finds the run complete,
so retrying it is both safe and the way it heals.
"""

import time
import uuid
from collections.abc import Callable
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from structlog.contextvars import bound_contextvars

from qs_template import Database
from qs_template.jobs import Handler, Job, JobQueue, ProgressReporter, Submitted
from qs_template.logging import get_logger
from qs_trading.adapters.feed_client import FeedClient, HttpxFeedClient, StaticToken
from qs_trading.adapters.file_environment import FixtureError, file_environments
from qs_trading.adapters.http_environment import (
    PermanentFeedError,
    ReplayFeed,
    SimulationPathFeed,
)
from qs_trading.domain.accounting import AccountingError
from qs_trading.domain.strategies import UnknownStrategyKind
from qs_trading.domain.strategy import LookAheadError
from qs_trading.engine.core import EngineError
from qs_trading.engine.runner import run_portfolio
from qs_trading.engine.store import PortfolioNotFound, PortfolioStore
from qs_trading.models import job
from qs_trading.ports.market_environment import (
    EnvironmentRef,
    FingerprintChanged,
    MarketEnvironment,
    MarketEnvironmentError,
    MissingAdjustedPrices,
)
from qs_trading.projections.fold import ProjectionError
from qs_trading.settings import TradingSettings

__all__ = [
    "BUNDLED_DEMO_ENVIRONMENTS",
    "ENGINE_RUN",
    "PERMANENT_ERRORS",
    "EnvironmentFactory",
    "NoMarketAdapter",
    "build_handlers",
    "engine_run_handler",
    "engine_run_key",
    "environment_factory",
    "fail_permanently",
    "is_permanent",
    "job_queue",
    "no_environments",
    "submit_engine_run",
]

log = get_logger(__name__)

ENGINE_RUN = "engine.run"

EnvironmentFactory = Callable[[EnvironmentRef], MarketEnvironment]
"""Opens the market environment a portfolio is bound to."""


class NoMarketAdapter(MarketEnvironmentError):
    """No adapter is configured for the portfolio's kind of environment."""


def no_environments(ref: EnvironmentRef) -> MarketEnvironment:
    """The factory until the HTTP adapters (A17) are wired: every run fails clearly."""
    raise NoMarketAdapter(f"no market adapter is configured for {ref.env_type} {ref.env_id}")


PERMANENT_ERRORS: tuple[type[Exception], ...] = (
    PortfolioNotFound,
    EngineError,  # ResumeMismatch included
    FingerprintChanged,
    MissingAdjustedPrices,
    FixtureError,
    NoMarketAdapter,
    PermanentFeedError,  # 401/403/404/409/501, other 4xx, a contract violation
    ProjectionError,
    UnknownStrategyKind,
    ValidationError,
    AccountingError,
    LookAheadError,
)
"""Failures of an ``engine.run`` job that a retry cannot fix: they follow from the stored
spec, the portfolio's bound fingerprint or the environment's data, which a retry reads
again unchanged. Deliberately not listed: :class:`MarketEnvironmentError` as a whole (the
HTTP adapters raise ``FeedUnavailable``, one of them, for a feed that is only down for now:
429, 5xx other than 501, timeouts and connection errors), plain ``ValueError`` and
``RuntimeError``, and :class:`~qs_trading.engine.store.ChainConflict`."""


def is_permanent(error: BaseException) -> bool:
    """Whether a failed run should end its job for good rather than be retried."""
    return isinstance(error, PERMANENT_ERRORS)


async def fail_permanently(
    database: Database, queue: JobQueue, claimed: Job, error: BaseException
) -> str | None:
    """Marks ``claimed`` failed with no retry (K1 ``fail(retry=False)``) while the job is
    still running on this claim. Returns the new status, or ``None`` when the claim was
    already lost (the job is then left to its new owner)."""
    t = queue.table
    message = f"{type(error).__name__}: {error}"
    async with database.transaction() as session:
        owner = await session.scalar(
            select(t.c.lease_owner)
            .where(t.c.id == claimed.id, t.c.status == "running", t.c.attempts == claimed.attempt)
            .with_for_update()
        )
        if owner is None:
            return None
        return await queue.fail(session, claimed.id, str(owner), message, retry=False)


BUNDLED_DEMO_ENVIRONMENTS = Path(__file__).resolve().parent / "demo" / "environments"
"""The demo fixtures shipped inside the package (and so inside the image)."""


def _local_factory(settings: TradingSettings) -> EnvironmentFactory:
    """The demo fixtures when ``QS_TRADING_DEMO_ENVIRONMENTS`` is set (``bundled`` = the
    package's own), otherwise none."""
    configured = settings.trading_demo_environments
    if not configured:
        return no_environments
    directory = BUNDLED_DEMO_ENVIRONMENTS if configured == "bundled" else Path(configured)
    if not directory.is_dir():
        raise ValueError(f"QS_TRADING_DEMO_ENVIRONMENTS: {directory} is not a directory")
    return file_environments(directory)


def _feed_client(settings: TradingSettings, base_url: str) -> FeedClient:
    # K3 (#85): build ServiceClientFeed (adapters/feed_client.py) here instead
    if settings.service_token is None:
        raise ValueError("QS_SERVICE_TOKEN must be set to read the market feeds")
    return HttpxFeedClient(
        base_url,
        StaticToken(settings.service_token),
        timeout_seconds=settings.trading_feed_timeout_seconds,
    )


def environment_factory(
    settings: TradingSettings,
    *,
    market: FeedClient | None = None,
    simulation: FeedClient | None = None,
) -> EnvironmentFactory:
    """The environments the worker can run over. A replay is read from the market
    service's feed when ``QS_TRADING_MARKET_URL`` is set, a simulation path from the
    simulation service's when ``QS_TRADING_SIMULATION_URL`` is set (one client each,
    shared by every run of the worker; ``market`` and ``simulation`` replace them in
    tests). A kind with no URL falls back to the demo fixtures when
    ``QS_TRADING_DEMO_ENVIRONMENTS`` is set, otherwise to none. A configured directory that
    does not exist, or a feed URL without ``QS_SERVICE_TOKEN``, stops the worker from
    starting."""
    local = _local_factory(settings)
    if market is None and settings.trading_market_url:
        market = _feed_client(settings, settings.trading_market_url)
    if simulation is None and settings.trading_simulation_url:
        simulation = _feed_client(settings, settings.trading_simulation_url)
    if market is None and simulation is None:
        return local
    ttl = settings.trading_fingerprint_cache_seconds

    def open_environment(ref: EnvironmentRef) -> MarketEnvironment:
        if ref.env_type == "replay" and market is not None:
            return ReplayFeed(market, ref.env_id, fingerprint_ttl_seconds=ttl)
        if ref.env_type == "simulation" and simulation is not None and ref.path_index is not None:
            return SimulationPathFeed(
                simulation, ref.env_id, ref.path_index, fingerprint_ttl_seconds=ttl
            )
        return local(ref)

    return open_environment


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


def engine_run_handler(
    database: Database, environments: EnvironmentFactory, queue: JobQueue | None = None
) -> Handler:
    """The ``engine.run`` handler. ``queue`` only records a permanent failure; any queue
    over the service's ``job`` table will do."""
    jobs = queue or JobQueue(job)

    async def handle(claimed: Job, report: ProgressReporter) -> dict[str, object] | None:
        # A-NFR-14: every log line of the run carries the job and the portfolio
        portfolio = str(claimed.payload.get("portfolio_id"))
        with bound_contextvars(job_id=str(claimed.id), portfolio_id=portfolio):
            started, outcome = time.monotonic(), "raised"
            log.info("engine run started", attempt=claimed.attempt)
            try:
                result = await run_job(claimed, report)
                outcome = "completed" if result is not None else "failed permanently"
                return result
            finally:
                seconds = round(time.monotonic() - started, 3)
                log.info("engine run ended", outcome=outcome, duration_seconds=seconds)

    async def run_job(claimed: Job, report: ProgressReporter) -> dict[str, object] | None:
        try:
            portfolio_id = uuid.UUID(str(claimed.payload["portfolio_id"]))
            store = PortfolioStore(database, portfolio_id, run_id=claimed.id)
            spec = await store.load_spec()
            environment = environments(spec.environment)
            result = await run_portfolio(spec, environment, store, progress=report)
        except PERMANENT_ERRORS as exc:
            status = await fail_permanently(database, jobs, claimed, exc)
            log.warning(
                "job failed permanently" if status else "job failed after losing its claim",
                job_id=str(claimed.id),
                attempt=claimed.attempt,
                error=f"{type(exc).__name__}: {exc}",
            )
            return None
        return result.to_json()

    return handle


def build_handlers(
    database: Database,
    environments: EnvironmentFactory = no_environments,
    queue: JobQueue | None = None,
) -> dict[str, Handler]:
    """Every handler of the service, by job kind."""
    return {ENGINE_RUN: engine_run_handler(database, environments, queue)}
