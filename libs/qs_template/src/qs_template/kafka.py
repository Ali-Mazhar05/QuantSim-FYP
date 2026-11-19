"""Redpanda (Kafka protocol) adapters for the outbox relay and event consumers.

:class:`KafkaPublisher` is the :class:`~qs_template.messaging.Publisher` the outbox relay
uses: idempotent producer, every in-sync replica must acknowledge (``acks=all``).

:class:`EventConsumer` reads a consumer group's topics and, for each event, runs the
registered handler through :func:`~qs_template.messaging.handle_once` inside one
database transaction, then commits the offset. A crash between the two redelivers the
event, which ``handle_once`` then skips, so every event has exactly one effect. An event
that keeps failing is parked on ``<topic>.dlq`` after ``max_attempts`` so it cannot block
the partition, and is logged for investigation.
"""

import asyncio
from collections.abc import Mapping

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer, ConsumerRecord
from aiokafka.errors import KafkaError
from pydantic import ValidationError

from qs_template.db import Database
from qs_template.events import EventEnvelope
from qs_template.logging import get_logger
from qs_template.messaging import Handler, handle_once

log = get_logger(__name__)


class KafkaPublisher:
    def __init__(self, bootstrap_servers: str, *, client_id: str) -> None:
        self._producer = AIOKafkaProducer(
            bootstrap_servers=bootstrap_servers,
            client_id=client_id,
            acks="all",
            enable_idempotence=True,
            linger_ms=5,
            request_timeout_ms=10_000,
        )

    async def start(self) -> None:
        await self._producer.start()

    async def stop(self) -> None:
        await self._producer.stop()

    async def publish(self, topic: str, key: str, value: bytes) -> None:
        await self._producer.send_and_wait(topic, value=value, key=key.encode())

    async def ping(self) -> None:
        """Readiness: raises when the broker cannot be reached."""
        await self._producer.client.fetch_all_metadata()


class EventConsumer:
    def __init__(
        self,
        database: Database,
        *,
        bootstrap_servers: str,
        group: str,
        topics: list[str],
        handlers: Mapping[str, Handler],
        dead_letters: KafkaPublisher,
        max_attempts: int = 5,
        retry_seconds: float = 1.0,
    ) -> None:
        self._db = database
        self._group = group
        self._handlers = dict(handlers)
        self._dead_letters = dead_letters
        self._max_attempts = max_attempts
        self._retry_seconds = retry_seconds
        self._stopping = asyncio.Event()
        self._consumer = AIOKafkaConsumer(
            *topics,
            bootstrap_servers=bootstrap_servers,
            group_id=group,
            client_id=group,
            enable_auto_commit=False,
            auto_offset_reset="earliest",
            isolation_level="read_committed",
        )

    async def run(self) -> None:
        await self._consumer.start()
        try:
            while not self._stopping.is_set():
                batches = await self._consumer.getmany(timeout_ms=500, max_records=100)
                for partition, records in batches.items():
                    for record in records:
                        await self._process(record)
                        await self._consumer.commit({partition: record.offset + 1})
        finally:
            await self._consumer.stop()

    def stop(self) -> None:
        self._stopping.set()

    async def lag(self) -> dict[str, int]:
        """Messages not yet processed, per partition (NFR-OBS-003)."""
        partitions = list(self._consumer.assignment())
        if not partitions:
            return {}
        ends = await self._consumer.end_offsets(partitions)
        result: dict[str, int] = {}
        for tp in partitions:
            committed = await self._consumer.committed(tp) or 0
            result[f"{tp.topic}[{tp.partition}]"] = max(ends[tp] - committed, 0)
        return result

    async def _process(self, record: ConsumerRecord[bytes, bytes]) -> None:
        try:
            event = EventEnvelope.from_bytes(record.value or b"")
        except ValidationError as exc:
            await self._park(record, f"not a valid event envelope: {exc.error_count()} errors")
            return
        handler = self._handlers.get(event.event_type)
        if handler is None:
            return  # this consumer does not care about this event type

        for attempt in range(1, self._max_attempts + 1):
            try:
                async with self._db.transaction() as session:
                    await handle_once(session, self._group, event, handler)
                return
            except Exception as exc:
                log.warning(
                    "event handler failed",
                    event_id=str(event.event_id),
                    event_type=event.event_type,
                    attempt=attempt,
                    error=str(exc),
                )
                if attempt < self._max_attempts:
                    await asyncio.sleep(self._retry_seconds * attempt)
        await self._park(record, f"handler failed {self._max_attempts} times")

    async def _park(self, record: ConsumerRecord[bytes, bytes], reason: str) -> None:
        dlq = f"{record.topic}.dlq"
        key = (record.key or b"").decode(errors="replace")
        log.error("event parked on the dead-letter topic", topic=dlq, reason=reason, key=key)
        try:
            await self._dead_letters.publish(dlq, key, record.value or b"")
        except KafkaError as exc:
            # Do not lose it: stop here so the offset is not committed and it is retried
            log.error("could not park event", topic=dlq, error=str(exc))
            raise
