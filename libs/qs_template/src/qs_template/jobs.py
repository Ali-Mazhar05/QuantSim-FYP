"""Background jobs in a service's own database (K1).

Every long-running piece of work (an engine run, a calibration, a Monte Carlo run, a TDA
analysis) is a row in the service's ``job`` table. The API inserts it and answers 202
straight away; worker processes claim jobs, run them and record the outcome.

Guarantees:

- **Idempotent submit.** Every job has a unique idempotency key; submitting the same key
  again returns the job that already exists instead of creating a second one.
- **Single claim.** Workers claim with ``FOR UPDATE SKIP LOCKED``, so two workers never
  run the same job at once and never wait for each other.
- **Lease and reclaim.** A claimed job carries a lease that its worker extends with
  heartbeats. When a worker dies the lease runs out and another worker claims the job
  again, up to ``max_attempts`` times; after that it is marked failed.
- **Fencing.** Heartbeat, complete and fail only succeed for the worker that holds the
  current lease, so a worker that lost its lease cannot overwrite the new owner's work.

A service adds the table to its own metadata with :func:`job_table` and creates it in a
migration; :class:`JobQueue` works on that table, and :class:`Worker` runs the claim,
heartbeat and complete loop around a set of handlers.
"""

import asyncio
import os
import socket
import uuid
from collections.abc import Awaitable, Callable, Collection, Coroutine, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    MetaData,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
    and_,
    case,
    func,
    or_,
    select,
    text,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from qs_template.db import Database
from qs_template.logging import get_logger

log = get_logger(__name__)

JOB_STATUSES = ("queued", "running", "succeeded", "failed")


def job_table(metadata: MetaData, name: str = "job") -> Table:
    """The job table, added to ``metadata``. Create it in the service's first migration."""
    return Table(
        name,
        metadata,
        Column("id", Uuid, primary_key=True),
        Column("kind", Text, nullable=False),
        Column("idempotency_key", Text, nullable=False),
        Column("payload", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
        Column("status", Text, nullable=False, server_default=text("'queued'")),
        Column("progress", Float, nullable=False, server_default=text("0")),
        Column("attempts", Integer, nullable=False, server_default=text("0")),
        Column("max_attempts", Integer, nullable=False, server_default=text("3")),
        Column("lease_owner", Text),
        Column("lease_expires_at", DateTime(timezone=True)),
        Column("result", JSONB),
        Column("error", Text),
        Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
        Column("started_at", DateTime(timezone=True)),
        Column("finished_at", DateTime(timezone=True)),
        Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
        UniqueConstraint("idempotency_key", name=f"{name}_idempotency_key"),
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')", name=f"{name}_status"
        ),
        CheckConstraint("progress >= 0 AND progress <= 1", name=f"{name}_progress"),
        CheckConstraint("attempts >= 0 AND max_attempts >= 1", name=f"{name}_attempts"),
        Index(f"{name}_claimable", "status", "created_at"),
    )


@dataclass(frozen=True)
class Submitted:
    id: uuid.UUID
    created: bool  # False when the idempotency key already had a job


@dataclass(frozen=True)
class Job:
    """A claimed job, as its handler sees it."""

    id: uuid.UUID
    kind: str
    payload: dict[str, Any]
    attempt: int
    idempotency_key: str


@dataclass(frozen=True)
class JobState:
    id: uuid.UUID
    kind: str
    status: str
    progress: float
    attempts: int
    max_attempts: int
    error: str | None
    result: dict[str, Any] | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class IdempotencyConflict(ValueError):
    """The idempotency key already belongs to a job of another kind."""


class JobQueue:
    """Submit, claim, heartbeat, complete and fail jobs in one service's job table.

    Every method takes the caller's session and does not commit; the caller's
    transaction decides. Times come from the database clock, never the worker's.
    """

    def __init__(self, table: Table, *, lease_seconds: float = 60.0, max_attempts: int = 3) -> None:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be above zero")
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        self.table = table
        self.lease_seconds = lease_seconds
        self.max_attempts = max_attempts
        self._lease = timedelta(seconds=lease_seconds)

    async def submit(
        self,
        session: AsyncSession,
        kind: str,
        payload: Mapping[str, Any] | None = None,
        *,
        idempotency_key: str | None = None,
        max_attempts: int | None = None,
    ) -> Submitted:
        """Queue a job, or return the existing job with the same idempotency key."""
        t = self.table
        key = idempotency_key or str(uuid.uuid4())
        attempts = max_attempts or self.max_attempts
        if attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        new_id = (
            await session.execute(
                pg_insert(t)
                .values(
                    id=uuid.uuid4(),
                    kind=kind,
                    idempotency_key=key,
                    payload=dict(payload or {}),
                    max_attempts=attempts,
                )
                .on_conflict_do_nothing(index_elements=[t.c.idempotency_key])
                .returning(t.c.id)
            )
        ).scalar_one_or_none()
        if new_id is not None:
            return Submitted(new_id, created=True)
        existing = (
            await session.execute(select(t.c.id, t.c.kind).where(t.c.idempotency_key == key))
        ).one()
        if existing.kind != kind:
            raise IdempotencyConflict(
                f"idempotency key {key!r} already belongs to a {existing.kind} job"
            )
        return Submitted(existing.id, created=False)

    async def claim(
        self,
        session: AsyncSession,
        worker_id: str,
        kinds: Collection[str] | None = None,
    ) -> Job | None:
        """Take the oldest claimable job: queued, or running with an expired lease.

        Jobs whose lease ran out on their last allowed attempt are marked failed first.
        Returns ``None`` when there is nothing to do.
        """
        t = self.table
        now = func.now()
        await session.execute(
            update(t)
            .where(
                t.c.status == "running",
                t.c.lease_expires_at < now,
                t.c.attempts >= t.c.max_attempts,
            )
            .values(
                status="failed",
                error="the lease expired on the last allowed attempt",
                lease_owner=None,
                lease_expires_at=None,
                finished_at=now,
                updated_at=now,
            )
        )
        conditions = [
            or_(
                t.c.status == "queued",
                and_(t.c.status == "running", t.c.lease_expires_at < now),
            ),
            t.c.attempts < t.c.max_attempts,
        ]
        if kinds is not None:
            conditions.append(t.c.kind.in_(list(kinds)))
        picked = (
            select(t.c.id)
            .where(*conditions)
            .order_by(t.c.created_at, t.c.id)
            .limit(1)
            .with_for_update(skip_locked=True)
            .scalar_subquery()
        )
        row = (
            await session.execute(
                update(t)
                .where(t.c.id == picked)
                .values(
                    status="running",
                    attempts=t.c.attempts + 1,
                    lease_owner=worker_id,
                    lease_expires_at=now + self._lease,
                    started_at=func.coalesce(t.c.started_at, now),
                    error=None,
                    updated_at=now,
                )
                .returning(t.c.id, t.c.kind, t.c.payload, t.c.attempts, t.c.idempotency_key)
            )
        ).first()
        if row is None:
            return None
        return Job(
            id=row.id,
            kind=row.kind,
            payload=dict(row.payload),
            attempt=row.attempts,
            idempotency_key=row.idempotency_key,
        )

    def _owned(self, job_id: uuid.UUID, worker_id: str) -> Any:
        t = self.table
        return and_(t.c.id == job_id, t.c.status == "running", t.c.lease_owner == worker_id)

    async def heartbeat(
        self,
        session: AsyncSession,
        job_id: uuid.UUID,
        worker_id: str,
        progress: float | None = None,
    ) -> bool:
        """Extend the lease and optionally record progress (0 to 1). False when this
        worker no longer holds the lease; it must then stop working on the job."""
        t = self.table
        now = func.now()
        values: dict[str, Any] = {"lease_expires_at": now + self._lease, "updated_at": now}
        if progress is not None:
            values["progress"] = min(max(float(progress), 0.0), 1.0)
        row = (
            await session.execute(
                update(t).where(self._owned(job_id, worker_id)).values(**values).returning(t.c.id)
            )
        ).first()
        return row is not None

    async def complete(
        self,
        session: AsyncSession,
        job_id: uuid.UUID,
        worker_id: str,
        result: Mapping[str, Any] | None = None,
    ) -> bool:
        """Mark the job succeeded. False when this worker no longer holds the lease."""
        t = self.table
        now = func.now()
        row = (
            await session.execute(
                update(t)
                .where(self._owned(job_id, worker_id))
                .values(
                    status="succeeded",
                    progress=1.0,
                    result=None if result is None else dict(result),
                    error=None,
                    lease_owner=None,
                    lease_expires_at=None,
                    finished_at=now,
                    updated_at=now,
                )
                .returning(t.c.id)
            )
        ).first()
        return row is not None

    async def fail(
        self,
        session: AsyncSession,
        job_id: uuid.UUID,
        worker_id: str,
        error: str,
        *,
        retry: bool = True,
    ) -> str | None:
        """Record a failure. With ``retry`` the job is queued again while attempts
        remain. Returns the new status, or ``None`` when this worker no longer holds the
        lease."""
        t = self.table
        now = func.now()
        status: Any = (
            case((t.c.attempts < t.c.max_attempts, "queued"), else_="failed") if retry else "failed"
        )
        finished: Any = case((status == "failed", now), else_=None) if retry else now
        row = (
            await session.execute(
                update(t)
                .where(self._owned(job_id, worker_id))
                .values(
                    status=status,
                    error=error[:4000],
                    lease_owner=None,
                    lease_expires_at=None,
                    finished_at=finished,
                    updated_at=now,
                )
                .returning(t.c.status)
            )
        ).first()
        return None if row is None else str(row.status)

    async def get(self, session: AsyncSession, job_id: uuid.UUID) -> JobState | None:
        t = self.table
        row = (await session.execute(select(t).where(t.c.id == job_id))).first()
        if row is None:
            return None
        return JobState(
            id=row.id,
            kind=row.kind,
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


ProgressReporter = Callable[[float], Awaitable[None]]
Handler = Callable[[Job, ProgressReporter], Coroutine[Any, Any, Mapping[str, Any] | None]]


class LeaseLost(Exception):
    """Raised inside a handler when its worker no longer holds the job's lease."""


def default_worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:6]}"


class Worker:
    """Claims jobs of the kinds it has handlers for and runs them one at a time.

    While a handler runs, a background task renews the lease every third of the lease
    period. If the lease is lost the handler is cancelled and its outcome is dropped:
    the job already belongs to another worker. A handler that raises is recorded with
    :meth:`JobQueue.fail` (queued again while attempts remain).
    """

    def __init__(
        self,
        database: Database,
        queue: JobQueue,
        handlers: Mapping[str, Handler],
        *,
        worker_id: str | None = None,
        poll_seconds: float = 2.0,
    ) -> None:
        self.database = database
        self.queue = queue
        self.handlers = dict(handlers)
        self.worker_id = worker_id or default_worker_id()
        self.poll_seconds = poll_seconds
        self._stopping = asyncio.Event()

    def stop(self) -> None:
        self._stopping.set()

    async def run(self) -> None:
        log.info("worker started", worker_id=self.worker_id, kinds=sorted(self.handlers))
        while not self._stopping.is_set():
            ran = False
            try:
                ran = await self.run_once()
            except Exception:
                log.exception("worker loop error")
            if not ran:
                try:
                    await asyncio.wait_for(self._stopping.wait(), timeout=self.poll_seconds)
                except TimeoutError:
                    pass
        log.info("worker stopped", worker_id=self.worker_id)

    async def run_once(self) -> bool:
        """Claim and run one job. False when there was nothing to claim."""
        if not self.handlers:
            return False
        async with self.database.transaction() as session:
            job = await self.queue.claim(session, self.worker_id, kinds=self.handlers.keys())
        if job is None:
            return False
        await self._execute(job)
        return True

    async def _execute(self, job: Job) -> None:
        handler = self.handlers[job.kind]
        lost = asyncio.Event()

        async def report(progress: float) -> None:
            async with self.database.transaction() as session:
                held = await self.queue.heartbeat(session, job.id, self.worker_id, progress)
            if not held:
                lost.set()
                raise LeaseLost(f"lost the lease on job {job.id}")

        task: asyncio.Task[Mapping[str, Any] | None] = asyncio.create_task(handler(job, report))

        async def keep_lease() -> None:
            interval = self.queue.lease_seconds / 3
            while not task.done():
                await asyncio.sleep(interval)
                try:
                    async with self.database.transaction() as session:
                        held = await self.queue.heartbeat(session, job.id, self.worker_id)
                except Exception:
                    log.exception("heartbeat failed", job_id=str(job.id))
                    continue
                if not held:
                    lost.set()
                    task.cancel()
                    return

        keeper = asyncio.create_task(keep_lease())
        log.info("job started", job_id=str(job.id), kind=job.kind, attempt=job.attempt)
        try:
            result = await task
        except (asyncio.CancelledError, LeaseLost):
            if lost.is_set():
                log.warning("job abandoned: lease lost", job_id=str(job.id))
                return
            raise
        except Exception as exc:
            async with self.database.transaction() as session:
                status = await self.queue.fail(
                    session, job.id, self.worker_id, f"{type(exc).__name__}: {exc}"
                )
            log.warning("job failed", job_id=str(job.id), status=status, error=str(exc))
            return
        finally:
            keeper.cancel()
        async with self.database.transaction() as session:
            done = await self.queue.complete(session, job.id, self.worker_id, result)
        log.info(
            "job finished" if done else "job finished after losing its lease", job_id=str(job.id)
        )
