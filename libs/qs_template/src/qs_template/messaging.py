"""Reliable events between services: the transactional outbox and idempotent
consumers (NFR-REL-007, NFR-REL-008, NFR-OBS-003).

**Outbox.** A service never publishes directly. It calls :func:`add_event` inside the
same database transaction as the state change, so the change and its event commit
together or not at all. :class:`OutboxRelay` then publishes pending rows in order and
marks them published. If the broker is down, events wait in the table and go out when
it returns; nothing is lost and the original write is never blocked.

**Idempotent consumers.** Delivery is at-least-once, so an event may arrive twice.
:func:`handle_once` records the event id in ``processed_events`` in the same
transaction as the handler's effect; a redelivered event finds its id already there and
changes nothing.

Both tables are defined on :data:`messaging_metadata`; include it in a service's Alembic
``target_metadata`` so its migrations create them.
"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Identity,
    Index,
    Integer,
    MetaData,
    PrimaryKeyConstraint,
    Table,
    Text,
    Uuid,
    func,
    insert,
    select,
    text,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from qs_template.db import Database
from qs_template.events import EventEnvelope
from qs_template.logging import get_logger

log = get_logger(__name__)

messaging_metadata = MetaData()

outbox = Table(
    "outbox",
    messaging_metadata,
    Column("id", BigInteger, Identity(always=True), primary_key=True),
    Column("event_id", Uuid, nullable=False, unique=True),
    Column("topic", Text, nullable=False),
    Column("message_key", Text, nullable=False),
    Column("event_type", Text, nullable=False),
    Column("payload", JSONB, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("published_at", DateTime(timezone=True)),
    Column("attempts", Integer, nullable=False, server_default=text("0")),
    Column("last_error", Text),
    Index("outbox_pending", "id", postgresql_where=text("published_at IS NULL")),
)

processed_events = Table(
    "processed_events",
    messaging_metadata,
    Column("consumer_group", Text, nullable=False),
    Column("event_id", Uuid, nullable=False),
    Column("event_type", Text, nullable=False),
    Column("processed_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    PrimaryKeyConstraint("consumer_group", "event_id"),
)


async def add_event(session: AsyncSession, event: EventEnvelope) -> None:
    """Queue ``event`` for publication as part of the session's current transaction."""
    await session.execute(
        insert(outbox).values(
            event_id=event.event_id,
            topic=event.topic,
            message_key=event.aggregate_id,
            event_type=event.event_type,
            payload=event.model_dump(mode="json"),
        )
    )


class Publisher(Protocol):
    async def publish(self, topic: str, key: str, value: bytes) -> None:
        """Deliver one message; raise if the broker did not accept it."""


@dataclass(frozen=True)
class OutboxStats:
    pending: int
    oldest_pending_seconds: float


class OutboxRelay:
    """Publishes outbox rows in order. Safe to run in several processes at once: each
    batch is claimed with ``FOR UPDATE SKIP LOCKED``."""

    def __init__(
        self,
        database: Database,
        publisher: Publisher,
        *,
        batch_size: int = 100,
        idle_seconds: float = 0.5,
        max_backoff_seconds: float = 30,
    ) -> None:
        self._db = database
        self._publisher = publisher
        self._batch_size = batch_size
        self._idle = idle_seconds
        self._max_backoff = max_backoff_seconds
        self._stopping = asyncio.Event()

    async def publish_batch(self) -> int:
        """Publish up to one batch; returns how many rows were published. Stops at the
        first failure so events about an aggregate never go out of order."""
        published = 0
        async with self._db.transaction() as session:
            rows = (
                await session.execute(
                    select(outbox.c.id, outbox.c.topic, outbox.c.message_key, outbox.c.payload)
                    .where(outbox.c.published_at.is_(None))
                    .order_by(outbox.c.id)
                    .limit(self._batch_size)
                    .with_for_update(skip_locked=True)
                )
            ).all()
            for row in rows:
                value = EventEnvelope.model_validate(row.payload).to_bytes()
                try:
                    await self._publisher.publish(row.topic, row.message_key, value)
                except Exception as exc:
                    await session.execute(
                        update(outbox)
                        .where(outbox.c.id == row.id)
                        .values(attempts=outbox.c.attempts + 1, last_error=str(exc)[:1000])
                    )
                    log.warning("outbox publish failed", outbox_id=row.id, error=str(exc))
                    break
                await session.execute(
                    update(outbox)
                    .where(outbox.c.id == row.id)
                    .values(published_at=func.now(), attempts=outbox.c.attempts + 1)
                )
                published += 1
        return published

    async def run(self) -> None:
        """Publish until :meth:`stop` is called, backing off while the broker fails."""
        backoff = self._idle
        while not self._stopping.is_set():
            try:
                count = await self.publish_batch()
                pending = await self.stats()
            except Exception as exc:
                log.warning("outbox relay error", error=str(exc))
                count, pending = 0, OutboxStats(pending=1, oldest_pending_seconds=0)
            if count == self._batch_size:
                backoff = self._idle
                continue
            if pending.pending and count == 0:
                backoff = min(backoff * 2, self._max_backoff)
            else:
                backoff = self._idle
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=backoff)
            except TimeoutError:
                pass

    def stop(self) -> None:
        self._stopping.set()

    async def stats(self) -> OutboxStats:
        """Backlog size and age of the oldest unpublished event (NFR-OBS-003)."""
        async with self._db.transaction() as session:
            row = (
                await session.execute(
                    select(func.count(), func.min(outbox.c.created_at)).where(
                        outbox.c.published_at.is_(None)
                    )
                )
            ).one()
        count, oldest = int(row[0]), row[1]
        age = (datetime.now(UTC) - oldest).total_seconds() if oldest else 0.0
        return OutboxStats(pending=count, oldest_pending_seconds=max(age, 0.0))


Handler = Callable[[AsyncSession, EventEnvelope], Awaitable[None]]


async def handle_once(
    session: AsyncSession, consumer_group: str, event: EventEnvelope, handler: Handler
) -> bool:
    """Apply ``handler`` to ``event`` unless this consumer group already processed it.

    Runs in the caller's transaction, so recording the event and the handler's effect
    commit together. Returns False for a duplicate, which is then skipped.
    """
    first_time = (
        await session.execute(
            pg_insert(processed_events)
            .values(
                consumer_group=consumer_group,
                event_id=event.event_id,
                event_type=event.event_type,
            )
            .on_conflict_do_nothing()
            .returning(processed_events.c.event_id)
        )
    ).scalar_one_or_none()
    if first_time is None:
        log.info("duplicate event skipped", event_id=str(event.event_id), group=consumer_group)
        return False
    await handler(session, event)
    return True
