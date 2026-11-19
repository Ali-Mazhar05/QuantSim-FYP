import asyncio
import os
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable

import pytest
from aiokafka import AIOKafkaConsumer
from sqlalchemy import Column, MetaData, Table, Text, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from qs_template import Database
from qs_template.events import EventEnvelope
from qs_template.kafka import EventConsumer, KafkaPublisher
from qs_template.messaging import OutboxRelay, add_event, messaging_metadata

pytestmark = [pytest.mark.db, pytest.mark.kafka]

projection = MetaData()
seen = Table("seen", projection, Column("symbol", Text, primary_key=True))


@pytest.fixture
def bootstrap() -> str:
    return os.environ["TEST_KAFKA_BOOTSTRAP"]


@pytest.fixture
async def db(database: Database) -> Database:
    async with database.engine.begin() as connection:
        await connection.run_sync(messaging_metadata.create_all)
        await connection.run_sync(projection.create_all)
    return database


@pytest.fixture
async def publisher(bootstrap: str) -> AsyncIterator[KafkaPublisher]:
    producer = KafkaPublisher(bootstrap, client_id="tests")
    await producer.start()
    try:
        yield producer
    finally:
        await producer.stop()


def event(aggregate_type: str, symbol: str) -> EventEnvelope:
    return EventEnvelope(
        event_type="instrument.created",
        producer="market",
        aggregate_type=aggregate_type,
        aggregate_id=symbol,
        data={"symbol": symbol},
    )


async def eventually(condition: Callable[[], Awaitable[bool]]) -> None:
    # Polls the database, which has no event to wait on
    async with asyncio.timeout(30):
        while not await condition():  # noqa: ASYNC110
            await asyncio.sleep(0.2)


async def symbols(db: Database) -> list[str]:
    async with db.transaction() as session:
        return sorted(r[0] for r in await session.execute(select(seen.c.symbol)))


async def record(session: AsyncSession, e: EventEnvelope) -> None:
    await session.execute(insert(seen).values(symbol=e.aggregate_id))


def consumer_for(
    db: Database, bootstrap: str, topic: str, publisher: KafkaPublisher, handler: object
) -> EventConsumer:
    return EventConsumer(
        db,
        bootstrap_servers=bootstrap,
        group=f"tests-{uuid.uuid4().hex[:8]}",
        topics=[topic],
        handlers={"instrument.created": handler},  # type: ignore[dict-item]
        dead_letters=publisher,
        max_attempts=2,
        retry_seconds=0.1,
    )


async def test_outbox_events_reach_consumers_exactly_once(
    db: Database, bootstrap: str, publisher: KafkaPublisher
) -> None:
    aggregate = f"inst{uuid.uuid4().hex[:8]}"
    first = event(aggregate, "AAPL")
    async with db.transaction() as session:
        await add_event(session, first)
        await add_event(session, event(aggregate, "MSFT"))
    await OutboxRelay(db, publisher).publish_batch()
    # The broker redelivers the first event (at-least-once delivery)
    await publisher.publish(first.topic, first.aggregate_id, first.to_bytes())

    consumer = consumer_for(db, bootstrap, first.topic, publisher, record)
    task = asyncio.create_task(consumer.run())
    try:

        async def both_seen() -> bool:
            return await symbols(db) == ["AAPL", "MSFT"]

        await eventually(both_seen)
        await asyncio.sleep(2)  # give the duplicate time to arrive and be skipped
        assert await symbols(db) == ["AAPL", "MSFT"]
    finally:
        consumer.stop()
        await task


async def test_a_poison_event_is_parked_and_the_stream_moves_on(
    db: Database, bootstrap: str, publisher: KafkaPublisher
) -> None:
    aggregate = f"inst{uuid.uuid4().hex[:8]}"
    poison, good = event(aggregate, "BAD"), event(aggregate, "GOOD")
    for e in (poison, good):
        await publisher.publish(e.topic, e.aggregate_id, e.to_bytes())

    async def fails_on_bad(session: AsyncSession, e: EventEnvelope) -> None:
        if e.aggregate_id == "BAD":
            raise ValueError("cannot apply this event")
        await record(session, e)

    consumer = consumer_for(db, bootstrap, poison.topic, publisher, fails_on_bad)
    task = asyncio.create_task(consumer.run())
    try:

        async def good_seen() -> bool:
            return await symbols(db) == ["GOOD"]

        await eventually(good_seen)
    finally:
        consumer.stop()
        await task

    parked = await read_topic(bootstrap, f"{poison.topic}.dlq")
    assert [EventEnvelope.from_bytes(v).aggregate_id for v in parked] == ["BAD"]


async def test_a_malformed_message_is_parked(
    db: Database, bootstrap: str, publisher: KafkaPublisher
) -> None:
    topic = f"quantsim.market.inst{uuid.uuid4().hex[:8]}"
    await publisher.publish(topic, "x", b"this is not an event")
    good = EventEnvelope(
        event_type="instrument.created",
        producer="market",
        aggregate_type=topic.rsplit(".", 1)[1],
        aggregate_id="GOOD",
    )
    await publisher.publish(topic, "GOOD", good.to_bytes())

    consumer = consumer_for(db, bootstrap, topic, publisher, record)
    task = asyncio.create_task(consumer.run())
    try:

        async def good_seen() -> bool:
            return await symbols(db) == ["GOOD"]

        await eventually(good_seen)
    finally:
        consumer.stop()
        await task

    assert await read_topic(bootstrap, f"{topic}.dlq") == [b"this is not an event"]


async def read_topic(bootstrap: str, topic: str) -> list[bytes]:
    reader = AIOKafkaConsumer(
        topic,
        bootstrap_servers=bootstrap,
        group_id=None,
        auto_offset_reset="earliest",
        enable_auto_commit=False,
    )
    await reader.start()
    try:
        batches = await reader.getmany(timeout_ms=5000)
        return [r.value or b"" for records in batches.values() for r in records]
    finally:
        await reader.stop()
