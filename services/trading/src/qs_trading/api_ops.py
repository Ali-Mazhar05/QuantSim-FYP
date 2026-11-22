"""Operational metrics of the Trading service, under ``/api/trading`` (A-NFR-14,
NFR-OBS-002/003).

Admins only:
    GET /ops/metrics?recent=   queue depth, job durations and outbox backlog

``queue`` counts the ``engine.run`` jobs by status, with the age of the oldest queued
one. ``durations`` covers the ``recent`` most recently finished ``engine.run`` jobs
(succeeded or failed; default 100): count, p50, p95 and max of ``finished_at -
started_at``, where ``started_at`` is the first claim, so a retried job counts its
retries. ``outbox`` is the number of events not yet published and the age of the oldest.
Ages and durations are seconds; every age is measured against the database's clock.

The figures come from an :class:`OpsReader` made per request from the request's session,
so the route can be exercised without a database by handing :func:`build_routers`
another reader.
"""

import math
from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime
from typing import Annotated, Protocol

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

from qs_template.auth import Authenticator, Principal, Role
from qs_template.messaging import outbox
from qs_trading.jobs import ENGINE_RUN
from qs_trading.models import job
from qs_trading.schemas import JobDurationsOut, JobQueueOut, OpsMetricsOut, OutboxBacklogOut

__all__ = [
    "DEFAULT_RECENT",
    "MAX_RECENT",
    "OpsDependency",
    "OpsFactory",
    "OpsReader",
    "SqlOpsReader",
    "build_ops_routers",
    "durations_out",
    "percentile",
]

DEFAULT_RECENT = 100
MAX_RECENT = 1000


def percentile(ordered: Sequence[float], share: float) -> float | None:
    """Nearest-rank percentile of ascending ``ordered`` (``share`` in (0, 1]); ``None``
    for no values. The result is always one of the values."""
    if not ordered:
        return None
    # Rounded first so that 20 x 0.95 is rank 19, not 20 by a binary rounding error
    rank = max(1, math.ceil(round(len(ordered) * share, 9)))
    return ordered[min(rank, len(ordered)) - 1]


def durations_out(seconds: Sequence[float], window: int) -> JobDurationsOut:
    ordered = sorted(seconds)
    return JobDurationsOut(
        window=window,
        count=len(ordered),
        p50_seconds=percentile(ordered, 0.5),
        p95_seconds=percentile(ordered, 0.95),
        max_seconds=ordered[-1] if ordered else None,
    )


def _age(now: datetime, then: datetime | None) -> float | None:
    return None if then is None else max((now - then).total_seconds(), 0.0)


class OpsReader(Protocol):
    async def ops_metrics(self, recent: int) -> OpsMetricsOut:
        """The service's figures, durations over the ``recent`` last finished jobs."""
        ...


OpsFactory = Callable[[AsyncSession], OpsReader]
OpsDependency = Callable[..., Awaitable[OpsReader]]


class SqlOpsReader:
    """Reads the figures from trading_db's ``job`` and ``outbox`` tables."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def ops_metrics(self, recent: int) -> OpsMetricsOut:
        session = self._session
        now = (await session.execute(select(func.now()))).scalar_one()
        by_status: dict[str, int] = {}
        oldest_queued: datetime | None = None
        rows = await session.execute(
            select(job.c.status, func.count(), func.min(job.c.created_at))
            .where(job.c.kind == ENGINE_RUN)
            .group_by(job.c.status)
        )
        for status, count, oldest in rows:
            by_status[str(status)] = int(count)
            if status == "queued":
                oldest_queued = oldest
        finished = await session.execute(
            select(job.c.started_at, job.c.finished_at)
            .where(
                job.c.kind == ENGINE_RUN,
                job.c.finished_at.is_not(None),
                job.c.started_at.is_not(None),
            )
            .order_by(job.c.finished_at.desc())
            .limit(recent)
        )
        seconds = [max((end - start).total_seconds(), 0.0) for start, end in finished]
        pending, oldest_pending = (
            await session.execute(
                select(func.count(), func.min(outbox.c.created_at)).where(
                    outbox.c.published_at.is_(None)
                )
            )
        ).one()
        return OpsMetricsOut(
            generated_at=now,
            queue=JobQueueOut(
                kind=ENGINE_RUN,
                queued=by_status.get("queued", 0),
                running=by_status.get("running", 0),
                succeeded=by_status.get("succeeded", 0),
                failed=by_status.get("failed", 0),
                oldest_queued_seconds=_age(now, oldest_queued),
            ),
            durations=durations_out(seconds, recent),
            outbox=OutboxBacklogOut(
                pending=int(pending), oldest_pending_seconds=_age(now, oldest_pending)
            ),
        )


def build_ops_routers(*, auth: Authenticator, ops: OpsDependency) -> list[APIRouter]:
    router = APIRouter(prefix="/ops", tags=["ops"])

    Admin = Annotated[Principal, Depends(auth.require(Role.ADMIN))]
    Reader = Annotated[OpsReader, Depends(ops)]

    @router.get("/metrics", responses={401: {}, 403: {}, 422: {}})
    async def get_ops_metrics(
        _: Admin,
        reader: Reader,
        recent: Annotated[
            int,
            Query(ge=1, le=MAX_RECENT, description="How many finished jobs the durations cover"),
        ] = DEFAULT_RECENT,
    ) -> OpsMetricsOut:
        return await reader.ops_metrics(recent)

    return [router]
