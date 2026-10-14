"""The instrument master (FR-MKT-001): admins add, annotate and retire instruments.

Retiring is non-destructive: the instrument and its history stay, it simply stops being
ingested. Every change is audited by the database and published as an event.
"""

import csv
import uuid
from importlib import resources
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from qs_market.models import instrument
from qs_market.schemas import InstrumentIn, InstrumentOut, InstrumentUpdate
from qs_template.errors import ServiceError
from qs_template.events import EventEnvelope
from qs_template.messaging import add_event


def _not_found(instrument_id: uuid.UUID) -> ServiceError:
    return ServiceError(
        404,
        "Instrument not found",
        f"No instrument {instrument_id}.",
        type_="urn:quantsim:problem:not-found",
    )


async def get(session: AsyncSession, instrument_id: uuid.UUID) -> InstrumentOut:
    row = (
        await session.execute(select(instrument).where(instrument.c.id == instrument_id))
    ).one_or_none()
    if row is None:
        raise _not_found(instrument_id)
    return InstrumentOut.model_validate(row)


async def list_all(session: AsyncSession, status: str | None) -> list[InstrumentOut]:
    query = select(instrument).order_by(instrument.c.symbol)
    if status:
        query = query.where(instrument.c.status == status)
    return [InstrumentOut.model_validate(r) for r in (await session.execute(query)).all()]


async def create(session: AsyncSession, body: InstrumentIn) -> InstrumentOut:
    try:
        new_id = (
            await session.execute(
                instrument.insert()
                .values(**body.model_dump(exclude={"vendor_symbol"}),
                        vendor_symbol=body.vendor_symbol or body.symbol)
                .returning(instrument.c.id)
            )
        ).scalar_one()
    except IntegrityError as exc:
        raise ServiceError(
            409,
            "Instrument already exists",
            f"{body.symbol} on {body.exchange} is already in the instrument master.",
            type_="urn:quantsim:problem:conflict",
        ) from exc
    created = await get(session, new_id)
    await _publish(session, "instrument.created", created)
    return created


async def annotate(
    session: AsyncSession, instrument_id: uuid.UUID, body: InstrumentUpdate
) -> InstrumentOut:
    changes = body.model_dump(exclude_none=True)
    await get(session, instrument_id)
    if changes:
        await session.execute(
            update(instrument)
            .where(instrument.c.id == instrument_id)
            .values(**changes, updated_at=func.now())
        )
    return await get(session, instrument_id)


async def retire(session: AsyncSession, instrument_id: uuid.UUID) -> InstrumentOut:
    current = await get(session, instrument_id)
    if current.status == "retired":
        return current
    await session.execute(
        update(instrument)
        .where(instrument.c.id == instrument_id)
        .values(status="retired", retired_at=func.now(), updated_at=func.now())
    )
    retired = await get(session, instrument_id)
    await _publish(session, "instrument.retired", retired)
    return retired


async def seed_universe(session: AsyncSession) -> int:
    """Load the starting universe (``data/universe.csv``); existing rows are kept.
    Returns how many instruments were added."""
    text = resources.files("qs_market").joinpath("data/universe.csv").read_text("utf-8")
    added = 0
    for row in csv.DictReader(line for line in text.splitlines() if not line.startswith("#")):
        body = InstrumentIn(**{k: v for k, v in row.items() if v})
        result = await session.execute(
            pg_insert(instrument)
            .values(**body.model_dump(exclude={"vendor_symbol"}),
                    vendor_symbol=body.vendor_symbol or body.symbol)
            .on_conflict_do_nothing(constraint="instrument_symbol_exchange_unique")
            .returning(instrument.c.id)
        )
        new_id = result.scalar_one_or_none()
        if new_id is not None:
            added += 1
            await _publish(session, "instrument.created", await get(session, new_id))
    return added


async def _publish(session: AsyncSession, event_type: str, item: InstrumentOut) -> None:
    data: dict[str, Any] = {
        "instrument_id": str(item.id),
        "symbol": item.symbol,
        "exchange": item.exchange,
        "asset_class": item.asset_class,
        "status": item.status,
    }
    await add_event(
        session,
        EventEnvelope(
            event_type=event_type,
            producer="market",
            aggregate_type="instrument",
            aggregate_id=str(item.id),
            data=data,
        ),
    )
