"""The ingestion run queue.

Runs are rows of ``ingestion_run``. A scheduled mode creates one run per day through the
unique idempotency key, and two runs for the same instruments and window cannot be active
together. One worker at a time executes, enforced by a PostgreSQL advisory lock held on a
dedicated connection for the whole execution.

Crash recovery needs no heartbeat column: the advisory lock dies with the connection of a
crashed worker, so whoever holds the lock knows that any run still ``running`` is an
orphan. :func:`claim_next` resets such runs to ``pending`` and runs them again; the
per-instrument transactions make the repeat safe.
"""

import uuid
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, insert, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from qs_market.models import ingestion_run
from qs_template import Database

WORKER_LOCK_KEY = 0x5153_4D4B_0001
CREATE_LOCK_KEY = 0x5153_4D4B_0002
ACTIVE = ("pending", "running")


class RunConflict(Exception):
    """An active run already covers the same instrument and window."""

    def __init__(self, run_id: uuid.UUID) -> None:
        super().__init__(f"run {run_id} is already active for this instrument and window")
        self.run_id = run_id


@dataclass(frozen=True)
class CreatedRun:
    id: uuid.UUID
    created: bool  # False when the idempotency key already had a run


@dataclass(frozen=True)
class ClaimedRun:
    id: uuid.UUID
    mode: str
    vendor: str
    window_start: date | None
    window_end: date | None
    instrument_ids: list[uuid.UUID] | None


async def create_run(
    session: AsyncSession,
    *,
    mode: str,
    window: tuple[date | None, date | None] | None,
    instrument_ids: Sequence[uuid.UUID] | None,
    idempotency_key: str | None,
    requested_by: str,
    vendor: str,
) -> CreatedRun:
    start, end = window or (None, None)
    ids = None if instrument_ids is None else sorted(str(i) for i in instrument_ids)
    await session.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": CREATE_LOCK_KEY})
    if idempotency_key is not None:
        existing = (
            await session.execute(
                select(ingestion_run.c.id).where(ingestion_run.c.idempotency_key == idempotency_key)
            )
        ).scalar_one_or_none()
        if existing is not None:
            return CreatedRun(existing, created=False)
    active = (
        await session.execute(
            select(ingestion_run.c.id, ingestion_run.c.instrument_ids)
            .where(
                ingestion_run.c.status.in_(ACTIVE),
                ingestion_run.c.window_start.is_not_distinct_from(start),
                ingestion_run.c.window_end.is_not_distinct_from(end),
            )
            .order_by(ingestion_run.c.created_at)
        )
    ).all()
    for row in active:
        if ids is None or row.instrument_ids is None or set(ids) & set(row.instrument_ids):
            raise RunConflict(row.id)
    run_id = (
        await session.execute(
            insert(ingestion_run)
            .values(
                mode=mode,
                vendor=vendor,
                requested_by=requested_by,
                window_start=start,
                window_end=end,
                instrument_ids=ids,
                idempotency_key=idempotency_key,
            )
            .returning(ingestion_run.c.id)
        )
    ).scalar_one()
    return CreatedRun(run_id, created=True)


@asynccontextmanager
async def worker_lock(database: Database) -> AsyncIterator[bool]:
    """Try to become the one executing worker. Yields False when another holds the lock."""
    async with database.engine.connect() as raw:
        connection = await raw.execution_options(isolation_level="AUTOCOMMIT")
        got = (
            await connection.execute(
                text("SELECT pg_try_advisory_lock(:k)"), {"k": WORKER_LOCK_KEY}
            )
        ).scalar_one()
        try:
            yield bool(got)
        finally:
            if got:
                await connection.execute(
                    text("SELECT pg_advisory_unlock(:k)"), {"k": WORKER_LOCK_KEY}
                )


async def claim_next(session: AsyncSession) -> ClaimedRun | None:
    """Recover orphaned runs, then take the oldest pending run. Call it only while
    holding :func:`worker_lock`."""
    await session.execute(
        update(ingestion_run)
        .where(ingestion_run.c.status == "running")
        .values(status="pending", started_at=None)
    )
    row = (
        await session.execute(
            select(ingestion_run)
            .where(ingestion_run.c.status == "pending")
            .order_by(ingestion_run.c.created_at, ingestion_run.c.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
    ).first()
    if row is None:
        return None
    await session.execute(
        update(ingestion_run)
        .where(ingestion_run.c.id == row.id)
        .values(status="running", started_at=func.now(), error=None)
    )
    return ClaimedRun(
        id=row.id,
        mode=row.mode,
        vendor=row.vendor,
        window_start=row.window_start,
        window_end=row.window_end,
        instrument_ids=None
        if row.instrument_ids is None
        else [uuid.UUID(i) for i in row.instrument_ids],
    )
