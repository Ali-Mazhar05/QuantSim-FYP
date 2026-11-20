"""A-NFR-14: every log line an ``engine.run`` job writes carries its job id and portfolio
id, and the run ends with a line giving its outcome and duration. Without a database: a
stand-in session answers the handler's few queries."""

import uuid
from collections.abc import AsyncIterator, MutableMapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, cast

import pytest
import structlog
from structlog.contextvars import get_contextvars, merge_contextvars
from structlog.testing import LogCapture

from qs_template import Database
from qs_template.jobs import Handler, Job, JobQueue
from qs_trading import jobs
from qs_trading.jobs import ENGINE_RUN, build_handlers
from qs_trading.models import job


class _Rows:
    def first(self) -> Any:
        return None  # no such portfolio


@dataclass
class _Session:
    error: Exception | None = None

    async def execute(self, *args: Any, **kwargs: Any) -> _Rows:
        if self.error is not None:
            raise self.error
        return _Rows()

    async def scalar(self, *args: Any, **kwargs: Any) -> Any:
        return "worker-1"  # the claim is still held


@dataclass
class _Database:
    session: _Session

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[_Session]:
        yield self.session


class _Queue(JobQueue):
    def __init__(self) -> None:
        super().__init__(job)

    async def fail(self, *args: Any, **kwargs: Any) -> str | None:
        return "failed"


@pytest.fixture
def captured(monkeypatch: pytest.MonkeyPatch) -> list[MutableMapping[str, Any]]:
    """The handler's log lines, with the context variables merged in as in production."""
    capture = LogCapture()
    logger = structlog.wrap_logger(None, processors=[merge_contextvars, capture])
    monkeypatch.setattr(jobs, "log", logger)
    return capture.entries


async def _no_progress(_: float) -> None:
    return None


def _claimed() -> Job:
    payload = {"portfolio_id": str(uuid.uuid4())}
    return Job(id=uuid.uuid4(), kind=ENGINE_RUN, payload=payload, attempt=1, idempotency_key="k")


def _handler(session: _Session) -> Handler:
    return build_handlers(cast(Database, _Database(session)), queue=_Queue())[ENGINE_RUN]


def _ids(claimed: Job) -> dict[str, str]:
    return {"job_id": str(claimed.id), "portfolio_id": claimed.payload["portfolio_id"]}


async def test_a_permanent_failure_logs_with_the_job_and_portfolio(
    captured: list[MutableMapping[str, Any]],
) -> None:
    claimed = _claimed()
    assert await _handler(_Session())(claimed, _no_progress) is None

    assert [e["event"] for e in captured] == [
        "engine run started",
        "job failed permanently",
        "engine run ended",
    ]
    for entry in captured:
        assert entry.items() >= _ids(claimed).items(), entry
    ended = captured[-1]
    assert ended["outcome"] == "failed permanently"
    assert ended["duration_seconds"] >= 0


async def test_a_transient_failure_still_ends_with_a_line_and_unbinds(
    captured: list[MutableMapping[str, Any]],
) -> None:
    claimed = _claimed()
    with pytest.raises(ConnectionError):
        await _handler(_Session(error=ConnectionError("reset")))(claimed, _no_progress)

    assert [e["event"] for e in captured] == ["engine run started", "engine run ended"]
    assert captured[-1].items() >= {**_ids(claimed), "outcome": "raised"}.items()
    # The ids are bound for the run only
    assert "job_id" not in get_contextvars() and "portfolio_id" not in get_contextvars()
