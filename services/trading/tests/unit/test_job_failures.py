"""Which ``engine.run`` failures end the job for good and which are retried, and that the
handler records a permanent one through K1's ``fail(retry=False)`` fenced by its claim,
without a database (a stand-in session answers the few queries the handler makes)."""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, cast

import pytest
from pydantic import BaseModel, ValidationError
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from qs_template import Database
from qs_template.jobs import Job, JobQueue
from qs_trading.adapters.file_environment import FixtureError
from qs_trading.domain.accounting import InsufficientCash
from qs_trading.domain.strategies import UnknownStrategyKind
from qs_trading.domain.strategy import LookAheadError
from qs_trading.engine.core import EngineError, ResumeMismatch
from qs_trading.engine.store import ChainConflict, PortfolioNotFound
from qs_trading.jobs import (
    ENGINE_RUN,
    NoMarketAdapter,
    build_handlers,
    fail_permanently,
    is_permanent,
    no_environments,
)
from qs_trading.models import job
from qs_trading.ports.market_environment import (
    EnvironmentRef,
    FingerprintChanged,
    MarketEnvironmentError,
    MissingAdjustedPrices,
)
from qs_trading.projections.fold import ProjectionError


class _Positive(BaseModel):
    value: int


def _validation_error() -> ValidationError:
    try:
        _Positive.model_validate({"value": "not a number"})
    except ValidationError as exc:
        return exc
    raise AssertionError("expected a validation error")


PERMANENT: list[Exception] = [
    PortfolioNotFound("p"),
    EngineError("no ticks"),
    ResumeMismatch("the hash differs"),
    FingerprintChanged("old", "new"),
    MissingAdjustedPrices("no adjusted closes"),
    FixtureError("cannot read the fixture"),
    NoMarketAdapter("none"),
    ProjectionError(3, "the books differ"),
    UnknownStrategyKind("astrology"),
    _validation_error(),
    InsufficientCash("short"),
    LookAheadError("tomorrow"),
]

TRANSIENT: list[Exception] = [
    ChainConflict("another writer"),
    OperationalError("SELECT 1", {}, Exception("connection refused")),
    ConnectionError("reset"),
    TimeoutError(),
    OSError("disk"),
    MarketEnvironmentError("feed unavailable"),
    ValueError("anything else"),
    RuntimeError("anything else"),
]


@pytest.mark.parametrize("error", PERMANENT, ids=lambda e: type(e).__name__)
def test_errors_a_retry_cannot_fix_are_permanent(error: Exception) -> None:
    assert is_permanent(error)


@pytest.mark.parametrize("error", TRANSIENT, ids=lambda e: type(e).__name__)
def test_database_connection_and_chain_conflict_errors_are_retried(error: Exception) -> None:
    assert not is_permanent(error)


def test_no_adapter_is_a_permanent_market_environment_error() -> None:
    with pytest.raises(NoMarketAdapter) as raised:
        no_environments(EnvironmentRef("replay", "e"))
    assert isinstance(raised.value, MarketEnvironmentError) and is_permanent(raised.value)


class _Result:
    def __init__(self, row: Any) -> None:
        self._row = row

    def first(self) -> Any:
        return self._row


@dataclass
class _Session:
    """Answers the portfolio lookup (``execute``) and the claim check (``scalar``)."""

    portfolio_error: Exception | None = None
    lease_owner: str | None = "worker-1"
    statements: list[str] = field(default_factory=list)

    async def execute(self, statement: Any, *args: Any, **kwargs: Any) -> _Result:
        self.statements.append(str(statement))
        if self.portfolio_error is not None:
            raise self.portfolio_error
        return _Result(None)  # no such portfolio

    async def scalar(self, statement: Any, *args: Any, **kwargs: Any) -> Any:
        self.statements.append(str(statement))
        return self.lease_owner


@dataclass
class _Database:
    session: _Session

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[_Session]:
        yield self.session


class _Queue(JobQueue):
    def __init__(self) -> None:
        super().__init__(job)
        self.failed: list[tuple[uuid.UUID, str, str, bool]] = []

    async def fail(
        self,
        session: AsyncSession,
        job_id: uuid.UUID,
        worker_id: str,
        error: str,
        *,
        retry: bool = True,
    ) -> str | None:
        self.failed.append((job_id, worker_id, error, retry))
        return "failed"


def _claimed(attempt: int = 1) -> Job:
    return Job(
        id=uuid.uuid4(),
        kind=ENGINE_RUN,
        payload={"portfolio_id": str(uuid.uuid4())},
        attempt=attempt,
        idempotency_key="k",
    )


async def _no_progress(_: float) -> None:
    return None


async def test_a_permanent_failure_is_recorded_without_retry_by_the_claim_owner() -> None:
    session = _Session()
    queue = _Queue()
    handler = build_handlers(cast(Database, _Database(session)), queue=queue)[ENGINE_RUN]
    claimed = _claimed(attempt=2)

    assert await handler(claimed, _no_progress) is None

    assert len(queue.failed) == 1
    job_id, worker_id, error, retry = queue.failed[0]
    assert (job_id, worker_id, retry) == (claimed.id, "worker-1", False)
    assert error.startswith("PortfolioNotFound: ")
    # The fail is fenced by the claim: still running, on this attempt, row locked
    check = session.statements[-1]
    assert "job.status" in check and "job.attempts" in check and "FOR UPDATE" in check


async def test_a_transient_failure_is_raised_for_the_worker_to_retry() -> None:
    session = _Session(portfolio_error=ConnectionError("connection reset"))
    queue = _Queue()
    handler = build_handlers(cast(Database, _Database(session)), queue=queue)[ENGINE_RUN]

    with pytest.raises(ConnectionError):
        await handler(_claimed(), _no_progress)
    assert queue.failed == []


async def test_a_lost_claim_is_not_failed() -> None:
    session = _Session(lease_owner=None)
    queue = _Queue()
    status = await fail_permanently(
        cast(Database, _Database(session)), queue, _claimed(), FixtureError("gone")
    )
    assert status is None and queue.failed == []
