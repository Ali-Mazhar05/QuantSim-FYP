"""Idempotent seed of the starting universe (``python -m qs_market.seed``).

Inserts the 40 instruments of :mod:`qs_market.data.universe`; a (symbol, exchange) that
already exists is left exactly as it is, so running it twice changes nothing and an
admin's later annotations survive. It reads no file from the network and no symbol
directory.
"""

import asyncio
import sys

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from qs_market.data.universe import CALENDAR, CURRENCY, UNIVERSE
from qs_market.models import instrument
from qs_market.settings import MarketSettings
from qs_template import Database
from qs_template.audit import set_audit_context
from qs_template.events import EventEnvelope
from qs_template.logging import configure_logging, get_logger
from qs_template.messaging import add_event

ACTOR = "seed"


async def seed_instruments(session: AsyncSession) -> int:
    """Add the missing instruments; returns how many were added."""
    await set_audit_context(session, user_id=ACTOR, request_id=None)
    added = 0
    for symbol, name, sector, exchange, asset_class in UNIVERSE:
        row = (
            await session.execute(
                insert(instrument)
                .values(
                    symbol=symbol,
                    name=name,
                    sector=sector,
                    exchange=exchange,
                    calendar=CALENDAR,
                    currency=CURRENCY,
                    asset_class=asset_class,
                    vendor_symbol=symbol,
                    status="active",
                )
                .on_conflict_do_nothing(constraint="instrument_symbol_exchange_unique")
                .returning(instrument.c.id)
            )
        ).first()
        if row is None:
            continue
        added += 1
        await add_event(
            session,
            EventEnvelope(
                event_type="instrument.created",
                producer="market",
                aggregate_type="instrument",
                aggregate_id=str(row.id),
                data={
                    "instrument_id": str(row.id),
                    "symbol": symbol,
                    "exchange": exchange,
                    "name": name,
                    "sector": sector,
                    "asset_class": asset_class,
                    "status": "active",
                    "actor_id": None,
                },
            ),
        )
    return added


async def _run() -> int:
    settings = MarketSettings()
    configure_logging(
        service=settings.service_name, environment=settings.environment, level=settings.log_level
    )
    log = get_logger(__name__)
    database = Database(settings)
    try:
        async with database.transaction() as session:
            added = await seed_instruments(session)
        log.info("instruments seeded", added=added, universe=len(UNIVERSE))
        return 0
    finally:
        await database.close()


def main() -> None:
    sys.exit(asyncio.run(_run()))


if __name__ == "__main__":
    main()
