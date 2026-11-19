import uuid

import pytest
from pydantic import ValidationError
from sqlalchemy import Column, Integer, MetaData, Table, Text, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from qs_template import Database
from qs_template.events import EventEnvelope
from qs_template.messaging import (
    OutboxRelay,
    add_event,
    handle_once,
    messaging_metadata,
    outbox,
)

business = MetaData()
instrument = Table(
    "instrument",
    business,
    Column("id", Integer, primary_key=True),
    Column("symbol", Text, nullable=False),
)


def event(aggregate_id: str = "AAPL", event_type: str = "instrument.created") -> EventEnvelope:
    return EventEnvelope(
        event_type=event_type,
        producer="market",
        aggregate_type="instrument",
        aggregate_id=aggregate_id,
        data={"symbol": aggregate_id},
    )


class RecordingPublisher:
    def __init__(self, fail_on: set[str] | None = None) -> None:
        self.sent: list[tuple[str, str, EventEnvelope]] = []
        self.fail_on = fail_on or set()

    async def publish(self, topic: str, key: str, value: bytes) -> None:
        if key in self.fail_on:
            raise ConnectionError("broker unavailable")
        self.sent.append((topic, key, EventEnvelope.from_bytes(value)))


@pytest.fixture
async def db(database: Database) -> Database:
    async with database.engine.begin() as connection:
        await connection.run_sync(messaging_metadata.create_all)
        await connection.run_sync(business.create_all)
    return database


async def pending(db: Database) -> list[str]:
    async with db.transaction() as session:
        rows = await session.execute(
            select(outbox.c.message_key)
            .where(outbox.c.published_at.is_(None))
            .order_by(outbox.c.id)
        )
        return [r[0] for r in rows]


def test_event_topic_and_round_trip() -> None:
    original = event()

    assert original.topic == "quantsim.market.instrument"
    assert EventEnvelope.from_bytes(original.to_bytes()) == original


@pytest.mark.parametrize("bad_type", ["created", "Instrument.Created", "instrument.", "a b.c"])
def test_event_types_are_dotted_lowercase(bad_type: str) -> None:
    with pytest.raises(ValidationError):
        event(event_type=bad_type)


@pytest.mark.db
async def test_event_commits_with_the_state_change(db: Database) -> None:
    async with db.transaction() as session:
        await session.execute(insert(instrument).values(id=1, symbol="AAPL"))
        await add_event(session, event("AAPL"))

    assert await pending(db) == ["AAPL"]


@pytest.mark.db
async def test_event_is_discarded_when_the_state_change_rolls_back(db: Database) -> None:
    with pytest.raises(RuntimeError):
        async with db.transaction() as session:
            await session.execute(insert(instrument).values(id=1, symbol="AAPL"))
            await add_event(session, event("AAPL"))
            raise RuntimeError("validation failed after the insert")

    assert await pending(db) == []
    async with db.transaction() as session:
        assert (await session.execute(select(instrument))).all() == []


@pytest.mark.db
async def test_relay_publishes_in_order_and_marks_rows(db: Database) -> None:
    async with db.transaction() as session:
        for symbol in ("AAPL", "MSFT", "AAPL"):
            await add_event(session, event(symbol))
    publisher = RecordingPublisher()

    published = await OutboxRelay(db, publisher).publish_batch()

    assert published == 3
    assert [key for _, key, _ in publisher.sent] == ["AAPL", "MSFT", "AAPL"]
    assert {topic for topic, _, _ in publisher.sent} == {"quantsim.market.instrument"}
    assert await pending(db) == []


@pytest.mark.db
async def test_broker_outage_delays_but_never_loses_events(db: Database) -> None:
    async with db.transaction() as session:
        for symbol in ("AAPL", "MSFT", "NVDA"):
            await add_event(session, event(symbol))
    relay_down = OutboxRelay(db, RecordingPublisher(fail_on={"MSFT"}))

    assert await relay_down.publish_batch() == 1
    # Stops at the failure, so NVDA does not overtake MSFT
    assert await pending(db) == ["MSFT", "NVDA"]
    stats = await relay_down.stats()
    assert stats.pending == 2

    recovered = RecordingPublisher()
    assert await OutboxRelay(db, recovered).publish_batch() == 2
    assert [key for _, key, _ in recovered.sent] == ["MSFT", "NVDA"]
    async with db.transaction() as session:
        attempts = (
            await session.execute(select(outbox.c.attempts).where(outbox.c.message_key == "MSFT"))
        ).scalar_one()
    assert attempts == 2


@pytest.mark.db
async def test_relays_in_parallel_never_publish_an_event_twice(db: Database) -> None:
    async with db.transaction() as session:
        for i in range(20):
            await add_event(session, event(f"SYM{i}"))
    first, second = RecordingPublisher(), RecordingPublisher()

    await OutboxRelay(db, first, batch_size=10).publish_batch()
    await OutboxRelay(db, second, batch_size=10).publish_batch()

    keys = [k for _, k, _ in first.sent] + [k for _, k, _ in second.sent]
    assert sorted(keys) == sorted(f"SYM{i}" for i in range(20))
    assert len(set(keys)) == 20


@pytest.mark.db
async def test_duplicate_delivery_changes_nothing(db: Database) -> None:
    delivered = event("AAPL")
    calls: list[uuid.UUID] = []

    async def handler(session: AsyncSession, e: EventEnvelope) -> None:
        calls.append(e.event_id)
        await session.execute(insert(instrument).values(id=len(calls), symbol=e.aggregate_id))

    for _ in range(3):
        async with db.transaction() as session:
            await handle_once(session, "risk", delivered, handler)

    assert calls == [delivered.event_id]
    async with db.transaction() as session:
        assert len((await session.execute(select(instrument))).all()) == 1


@pytest.mark.db
async def test_each_consumer_group_processes_an_event_once(db: Database) -> None:
    delivered = event("AAPL")
    seen: list[str] = []

    for group in ("risk", "ml", "risk"):

        async def handler(_: AsyncSession, __: EventEnvelope, group: str = group) -> None:
            seen.append(group)

        async with db.transaction() as session:
            await handle_once(session, group, delivered, handler)

    assert seen == ["risk", "ml"]


@pytest.mark.db
async def test_a_failed_handler_can_be_retried(db: Database) -> None:
    delivered = event("AAPL")
    attempts = 0

    async def flaky(session: AsyncSession, e: EventEnvelope) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise TimeoutError("downstream call timed out")
        await session.execute(insert(instrument).values(id=1, symbol=e.aggregate_id))

    with pytest.raises(TimeoutError):
        async with db.transaction() as session:
            await handle_once(session, "risk", delivered, flaky)
    async with db.transaction() as session:
        assert await handle_once(session, "risk", delivered, flaky) is True

    assert attempts == 2
