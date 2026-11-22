"""A service's local copy of market's instruments (I2-14, ARC §8.9, §8.12).

Market owns instruments. A service that refers to them keeps an ``instrument_ref`` table,
a projection of market's ``instrument.*`` events on the topic
``quantsim.market.instrument``, so it can show a symbol or check that an instrument is
still active without calling market on every request.

**Retired, never deleted.** ``instrument.retired`` sets ``status`` to ``retired``; the row
stays, so history that names the instrument still resolves.

**Exactly once.** :class:`~qs_template.kafka.EventConsumer` records each event in
``processed_events`` in the same transaction as its effect (:func:`handle_once`), so a
redelivered event changes nothing. Events of one instrument share a partition key (its
id), so they are applied in the order market wrote them.

**Currency.** Market's events do not carry the currency; Iteration 2 trades in USD only,
so a missing currency is stored as ``USD``.

A service defines the table with :func:`instrument_ref_table` in its own metadata (so its
migrations and schema tests cover it) and runs :func:`instrument_consumer` beside its
outbox relay.
"""

from typing import Any

from sqlalchemy import CheckConstraint, Column, DateTime, Index, MetaData, Table, Text, Uuid, func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from qs_template.db import Database
from qs_template.events import EventEnvelope
from qs_template.kafka import EventConsumer, KafkaPublisher

__all__ = [
    "DEFAULT_CURRENCY",
    "INSTRUMENT_EVENTS",
    "INSTRUMENT_TOPIC",
    "apply_instrument_event",
    "instrument_consumer",
    "instrument_ref_table",
]

INSTRUMENT_TOPIC = "quantsim.market.instrument"
INSTRUMENT_EVENTS = ("instrument.created", "instrument.annotated", "instrument.retired")
DEFAULT_CURRENCY = "USD"


def instrument_ref_table(metadata: MetaData) -> Table:
    """Defines ``instrument_ref`` on ``metadata``; call it once in a service's models."""
    return Table(
        "instrument_ref",
        metadata,
        Column("id", Uuid, primary_key=True),
        Column("symbol", Text, nullable=False),
        Column("name", Text),
        Column("sector", Text),
        Column("exchange", Text, nullable=False),
        Column("currency", Text, nullable=False),
        Column("asset_class", Text),
        Column("status", Text, nullable=False, server_default="active"),
        Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
        CheckConstraint("status IN ('active', 'retired')", name="instrument_ref_status_valid"),
        Index("instrument_ref_symbol", "symbol"),
    )


def instrument_values(event: EventEnvelope) -> dict[str, Any]:
    """The ``instrument_ref`` row one ``instrument.*`` event describes."""
    data = event.data
    status = "retired" if event.event_type == "instrument.retired" else data.get("status", "active")
    return {
        "id": data["instrument_id"],
        "symbol": data["symbol"],
        "name": data.get("name"),
        "sector": data.get("sector"),
        "exchange": data["exchange"],
        "currency": data.get("currency") or DEFAULT_CURRENCY,
        "asset_class": data.get("asset_class"),
        "status": status,
    }


async def apply_instrument_event(session: AsyncSession, table: Table, event: EventEnvelope) -> None:
    """Upserts the instrument one ``instrument.*`` event describes. Run it through
    :func:`handle_once` (the consumer does), so a redelivery is skipped."""
    values = instrument_values(event)
    statement = pg_insert(table).values(**values)
    statement = statement.on_conflict_do_update(
        index_elements=[table.c.id],
        set_={
            **{key: statement.excluded[key] for key in values if key != "id"},
            "updated_at": func.now(),
        },
    )
    await session.execute(statement)


def instrument_consumer(
    database: Database,
    table: Table,
    *,
    bootstrap_servers: str,
    service: str,
    dead_letters: KafkaPublisher,
) -> EventConsumer:
    """The consumer that keeps ``table`` in step with market, in the consumer group
    ``<service>.instrument-ref``. Run it with ``await consumer.run()``."""

    async def handle(session: AsyncSession, event: EventEnvelope) -> None:
        await apply_instrument_event(session, table, event)

    return EventConsumer(
        database,
        bootstrap_servers=bootstrap_servers,
        group=f"{service}.instrument-ref",
        topics=[INSTRUMENT_TOPIC],
        handlers=dict.fromkeys(INSTRUMENT_EVENTS, handle),
        dead_letters=dead_letters,
    )
