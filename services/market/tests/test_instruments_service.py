"""Instrument master service: add, annotate, retire, list, events and audit."""

import uuid
from datetime import date

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from qs_market.instruments import InstrumentService
from qs_template import Database, ServiceError
from qs_template.audit import set_audit_context
from tests import instrument_support as support
from tests.instrument_support import (
    NEW_INSTRUMENT,
    insert_bar,
)

database = support.database
session = support.session
pytestmark = pytest.mark.db

ADD = dict(NEW_INSTRUMENT)


async def test_add_creates_an_active_instrument_with_vendor_symbol_default(
    session: AsyncSession,
) -> None:
    created = await InstrumentService(session).add(**ADD)
    assert created["status"] == "active"
    assert created["vendor_symbol"] == "ZZTEST"
    assert created["retired_at"] is None
    assert created["price"] is None and created["change_pct"] is None


async def test_duplicate_symbol_and_exchange_is_a_409_naming_the_existing_one(
    session: AsyncSession,
) -> None:
    service = InstrumentService(session)
    first = await service.add(**ADD)
    await service.retire(first["id"])
    with pytest.raises(ServiceError) as error:
        await service.add(**ADD)
    assert error.value.status == 409
    assert error.value.extra == {"existing_id": str(first["id"]), "existing_status": "retired"}
    # The same symbol on another exchange is a different instrument
    other = await service.add(**{**ADD, "exchange": "XNYS"})
    assert other["id"] != first["id"]


async def test_annotate_changes_only_name_sector_and_notes(session: AsyncSession) -> None:
    service = InstrumentService(session)
    created = await service.add(**ADD)
    updated = await service.annotate(created["id"], name="New Name", notes="watch")
    assert (updated["name"], updated["sector"], updated["notes"]) == (
        "New Name",
        "Technology",
        "watch",
    )
    for field in ("symbol", "exchange", "currency", "asset_class", "status", "calendar"):
        assert updated[field] == created[field]
    with pytest.raises(TypeError):
        await service.annotate(created["id"], symbol="OTHER")  # type: ignore[call-arg]


async def test_retire_is_non_destructive_and_idempotent(session: AsyncSession) -> None:
    service = InstrumentService(session)
    created = await service.add(**ADD)
    await insert_bar(session, created["id"], date(2026, 1, 5), "10")
    first = await service.retire(created["id"])
    second = await service.retire(created["id"])
    assert first["status"] == "retired" and first["retired_at"] is not None
    assert second["retired_at"] == first["retired_at"]
    bars = (await session.execute(text("SELECT count(*) FROM bar"))).scalar_one()
    assert bars == 1
    events = (
        await session.execute(
            text("SELECT event_type FROM outbox WHERE event_type = 'instrument.retired'")
        )
    ).all()
    assert len(events) == 1
    assert (await service.get(created["id"]))["price"] == "10.00000000"
    with pytest.raises(ServiceError) as missing:
        await service.retire(uuid.uuid4())
    assert missing.value.status == 404


async def test_list_has_the_poc_shape_and_filters_by_status(session: AsyncSession) -> None:
    service = InstrumentService(session)
    aapl = await service.add(**{**ADD, "symbol": "AAPL"})
    kept = await service.add(**{**ADD, "symbol": "KO"})
    await service.retire(kept["id"])
    await insert_bar(session, aapl["id"], date(2026, 1, 5), "200")
    await insert_bar(session, aapl["id"], date(2026, 1, 6), "214.32")
    await insert_bar(session, aapl["id"], date(2026, 1, 2), "1")  # older, not used

    everything = {i["symbol"]: i for i in await service.list()}
    assert set(everything["AAPL"]) == {
        "id",
        "symbol",
        "name",
        "sector",
        "price",
        "change_pct",
        "status",
        "exchange",
        "asset_class",
    }
    assert everything["AAPL"]["price"] == "214.32000000"
    assert everything["AAPL"]["change_pct"] == "7.16"
    assert [i["symbol"] for i in await service.list("active")] == ["AAPL"]
    assert [i["symbol"] for i in await service.list("retired")] == ["KO"]


async def test_fewer_than_two_bars_gives_a_price_but_no_change(session: AsyncSession) -> None:
    service = InstrumentService(session)
    created = await service.add(**ADD)
    assert (await service.list())[0]["price"] is None
    await insert_bar(session, created["id"], date(2026, 1, 5), "12.5")
    listed = (await service.list())[0]
    assert listed["price"] == "12.50000000" and listed["change_pct"] is None


async def test_the_event_commits_with_the_write_and_rolls_back_with_it(
    database: Database,
) -> None:
    class Abort(Exception):
        pass

    with pytest.raises(Abort):
        async with database.transaction() as session:
            await InstrumentService(session).add(**ADD)
            raise Abort
    async with database.transaction() as session:
        assert (await session.execute(text("SELECT count(*) FROM outbox"))).scalar_one() == 0
        assert (await session.execute(text("SELECT count(*) FROM instrument"))).scalar_one() == 0
        service = InstrumentService(session)
        created = await service.add(**ADD)
        await service.annotate(created["id"], notes="x")
        await service.retire(created["id"])
    async with database.transaction() as session:
        rows = (
            await session.execute(
                text("SELECT event_type, topic, message_key FROM outbox ORDER BY id")
            )
        ).all()
    assert [r.event_type for r in rows] == [
        "instrument.created",
        "instrument.annotated",
        "instrument.retired",
    ]
    assert {r.topic for r in rows} == {"quantsim.market.instrument"}
    assert {r.message_key for r in rows} == {str(created["id"])}


async def test_audit_rows_record_the_actor(database: Database) -> None:
    actor = uuid.uuid4()
    async with database.transaction() as session:
        await set_audit_context(session, user_id=actor, request_id="req-42")
        service = InstrumentService(session, actor_id=actor)
        created = await service.add(**ADD)
        await service.annotate(created["id"], name="Renamed")
    async with database.transaction() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT operation, changed_by, request_id FROM audit_log"
                    " WHERE table_name = 'instrument' AND row_id = :id ORDER BY id"
                ),
                {"id": str(created["id"])},
            )
        ).all()
        event = (
            await session.execute(text("SELECT payload FROM outbox ORDER BY id LIMIT 1"))
        ).scalar_one()
    assert [(r.operation, r.changed_by, r.request_id) for r in rows] == [
        ("INSERT", str(actor), "req-42"),
        ("UPDATE", str(actor), "req-42"),
    ]
    assert event["data"]["actor_id"] == str(actor)
