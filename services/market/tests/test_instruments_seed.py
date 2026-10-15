"""The 40-instrument seed: complete, idempotent and valid for the database."""

import pytest
from sqlalchemy import text

from qs_market.data.universe import UNIVERSE
from qs_market.seed import seed_instruments
from qs_template import Database
from tests import instrument_support as support

database = support.database
pytestmark = pytest.mark.db


async def test_seed_loads_30_equities_and_10_etfs(database: Database) -> None:
    async with database.transaction() as session:
        assert await seed_instruments(session) == 40
    async with database.transaction() as session:
        rows = await session.execute(
            text("SELECT asset_class, count(*) FROM instrument GROUP BY asset_class")
        )
        counts = {row[0]: row[1] for row in rows}
        symbols = {r[0] for r in await session.execute(text("SELECT symbol FROM instrument"))}
        events = (await session.execute(text("SELECT count(*) FROM outbox"))).scalar_one()
    assert counts == {"equity": 30, "etf": 10}
    assert {"AAPL", "MSFT", "NVDA", "TSLA", "KO", "SPY"} <= symbols
    assert events == 40


async def test_seeding_twice_changes_nothing_and_keeps_admin_edits(database: Database) -> None:
    async with database.transaction() as session:
        await seed_instruments(session)
        await session.execute(text("UPDATE instrument SET notes = 'mine' WHERE symbol = 'AAPL'"))
    async with database.transaction() as session:
        assert await seed_instruments(session) == 0
    async with database.transaction() as session:
        total = (await session.execute(text("SELECT count(*) FROM instrument"))).scalar_one()
        notes = (
            await session.execute(text("SELECT notes FROM instrument WHERE symbol = 'AAPL'"))
        ).scalar_one()
        events = (await session.execute(text("SELECT count(*) FROM outbox"))).scalar_one()
    assert (total, notes, events) == (40, "mine", 40)


def test_the_universe_has_unique_rows_on_the_two_listing_exchanges() -> None:
    assert len(UNIVERSE) == 40
    assert len({(symbol, exchange) for symbol, _, _, exchange, _ in UNIVERSE}) == 40
    assert {exchange for _, _, _, exchange, _ in UNIVERSE} <= {"XNAS", "XNYS"}
