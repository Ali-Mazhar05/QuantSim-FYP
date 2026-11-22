"""instrument_ref follows market's instrument events (I2-14): created and annotated
instruments are upserted, a retired one is marked and kept, and a redelivered event
changes nothing, all through the consumer's exactly-once path (``handle_once``)."""

import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from pydantic import SecretStr
from sqlalchemy import func, select
from trading_db_support import TradingDb, migrated_database, run

from qs_template import Database
from qs_template.events import EventEnvelope
from qs_template.instrument_ref import apply_instrument_event
from qs_template.messaging import handle_once
from qs_trading.models import instrument_ref
from qs_trading.settings import TradingSettings

pytestmark = pytest.mark.db

GROUP = "trading.instrument-ref"


@pytest.fixture(scope="module")
def trading_db() -> Iterator[TradingDb]:
    with migrated_database() as database:
        yield database


def _database(url: str) -> Database:
    return Database(
        TradingSettings(
            database_url=SecretStr(url),
            redis_url=SecretStr("redis://127.0.0.1:1/0"),
            content_hash="test-hash",
        )
    )


def _event(event_type: str, instrument_id: uuid.UUID, **data: Any) -> EventEnvelope:
    return EventEnvelope(
        event_type=event_type,
        producer="market",
        aggregate_type="instrument",
        aggregate_id=str(instrument_id),
        data={
            "instrument_id": str(instrument_id),
            "symbol": "AAPL",
            "exchange": "NASDAQ",
            "name": "Apple Inc.",
            "sector": "Technology",
            "asset_class": "equity",
            "status": "active",
            **data,
        },
    )


async def _deliver(database: Database, event: EventEnvelope) -> bool:
    async def handler(session: Any, delivered: EventEnvelope) -> None:
        await apply_instrument_event(session, instrument_ref, delivered)

    async with database.transaction() as session:
        return await handle_once(session, GROUP, event, handler)


async def _row(database: Database, instrument_id: uuid.UUID) -> dict[str, Any] | None:
    async with database.transaction() as session:
        row = (
            await session.execute(
                select(instrument_ref).where(instrument_ref.c.id == instrument_id)
            )
        ).one_or_none()
    return dict(row._mapping) if row else None


def test_created_annotated_and_retired_events_project_onto_one_row(trading_db: TradingDb) -> None:
    async def scenario() -> None:
        database = _database(trading_db.app_url)
        instrument_id = uuid.uuid4()
        try:
            await _deliver(database, _event("instrument.created", instrument_id))
            row = await _row(database, instrument_id)
            assert row is not None
            assert (row["symbol"], row["status"], row["currency"]) == ("AAPL", "active", "USD")

            await _deliver(database, _event("instrument.annotated", instrument_id, sector="IT"))
            row = await _row(database, instrument_id)
            assert row is not None and row["sector"] == "IT"

            await _deliver(database, _event("instrument.retired", instrument_id))
            row = await _row(database, instrument_id)
            assert row is not None, "a retired instrument is kept"
            assert row["status"] == "retired"
        finally:
            await database.close()

    run(scenario())


def test_a_redelivered_event_changes_nothing(trading_db: TradingDb) -> None:
    async def scenario() -> None:
        database = _database(trading_db.app_url)
        instrument_id = uuid.uuid4()
        retired = _event("instrument.retired", instrument_id)
        try:
            await _deliver(database, _event("instrument.created", instrument_id))
            assert await _deliver(database, retired) is True
            # The same retirement again, then a stale re-delivery of the creation's twin
            # under the same id as the retirement: both are skipped
            assert await _deliver(database, retired) is False
            stale = retired.model_copy(update={"event_type": "instrument.created"})
            assert await _deliver(database, stale) is False
            row = await _row(database, instrument_id)
            assert row is not None and row["status"] == "retired"
            async with database.transaction() as session:
                count = await session.scalar(
                    select(func.count())
                    .select_from(instrument_ref)
                    .where(instrument_ref.c.id == instrument_id)
                )
            assert count == 1
        finally:
            await database.close()

    run(scenario())
