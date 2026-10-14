"""The whole chain on real bars: seeded instruments, the runner, the cleaning gate, the
database. The vendor is the recorded corpus (the same real responses the other tests in
this folder use), so the run is repeatable and spends no requests.

Each check is the ideal behaviour stated independently of the code that produces it:
numpy for returns, the exchange calendar for sessions, the corpus itself for corporate
actions. A re-run must change nothing.
"""

from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import numpy as np
import pytest
from pydantic import SecretStr
from sqlalchemy import func, select, text

from qs_market import calendars
from qs_market.models import (
    bar,
    corporate_action,
    data_gap,
    instrument,
    rejected_bar,
    return_series,
)
from qs_market.pipeline.runner import PipelineConfig, RunOutcome, run_next
from qs_market.pipeline.runs import create_run
from qs_market.seed import seed_instruments
from qs_market.settings import MarketSettings
from qs_template import Database
from qs_template.messaging import outbox

from .conftest import SYMBOLS, Records

pytestmark = [pytest.mark.realdata, pytest.mark.db]

TABLES = (
    "outbox, return_series, corporate_action, data_gap, rejected_bar, staging_bar, bar_revision, "
    "bar, ingestion_run_item, ingestion_run, instrument"
)
SPLITS = {
    "AAPL": {date(2020, 8, 31)},
    "NVDA": {date(2021, 7, 20), date(2024, 6, 10)},
    "TSLA": {date(2020, 8, 31), date(2022, 8, 25)},
}


class RecordedSource:
    """Serves the recorded real bars, filtered to the requested window like the vendor."""

    name = "recorded"

    def __init__(self, corpus: dict[str, Records]) -> None:
        self._corpus = corpus

    async def fetch_daily(self, symbol: str, start: date, end: date) -> list[dict[str, Any]]:
        low, high = start.isoformat(), end.isoformat()
        return [dict(r) for r in self._corpus[symbol] if low <= r["date"] <= high]


@pytest.fixture
async def db(migrated_database_url: str) -> AsyncIterator[Database]:
    settings = MarketSettings(
        database_url=SecretStr(migrated_database_url), redis_url=SecretStr("redis://unused")
    )
    database = Database(settings)
    async with database.transaction() as session:
        await session.execute(text(f"TRUNCATE {TABLES} CASCADE"))
        await seed_instruments(session)
    yield database
    async with database.transaction() as session:
        await session.execute(text(f"TRUNCATE {TABLES} CASCADE"))
    await database.close()


async def _run(db: Database, source: RecordedSource, window: tuple[date, date]) -> RunOutcome:
    async with db.transaction() as session:
        ids = (
            (await session.execute(select(instrument.c.id).where(instrument.c.symbol.in_(SYMBOLS))))
            .scalars()
            .all()
        )
        await create_run(
            session,
            mode="backfill",
            window=window,
            instrument_ids=list(ids),
            idempotency_key=None,
            requested_by="realdata",
            vendor="recorded",
        )
    outcome = await run_next(
        db,
        lambda run: source,
        PipelineConfig(backfill_start=window[0]),
        as_of=datetime.now(UTC),
    )
    assert outcome is not None
    return outcome


async def _count(db: Database, table: Any) -> int:
    async with db.transaction() as session:
        return (await session.execute(select(func.count()).select_from(table))).scalar_one()


@pytest.fixture
async def first_run(
    db: Database, corpus: dict[str, Records], window: tuple[date, date]
) -> RunOutcome:
    return await _run(db, RecordedSource(corpus), window)


async def test_the_run_succeeds_and_every_symbol_is_stored(
    db: Database, first_run: RunOutcome, corpus: dict[str, Records]
) -> None:
    assert first_run.status == "succeeded", first_run.error
    async with db.transaction() as session:
        rows = (
            await session.execute(
                select(instrument.c.symbol, func.count())
                .select_from(instrument.join(bar, bar.c.instrument_id == instrument.c.id))
                .where(instrument.c.symbol.in_(SYMBOLS))
                .group_by(instrument.c.symbol)
            )
        ).all()
    stored = {symbol: count for symbol, count in rows}
    assert set(stored) == set(SYMBOLS)
    for symbol in SYMBOLS:
        # Real vendor bars are clean: all of them are stored, once each
        assert stored[symbol] == len(corpus[symbol]), f"{symbol}: {stored[symbol]} bars"
    assert await _count(db, rejected_bar) == 0


@pytest.mark.parametrize("symbol", SYMBOLS)
async def test_stored_bars_are_exactly_the_vendor_values(
    db: Database, first_run: RunOutcome, corpus: dict[str, Records], symbol: str
) -> None:
    async with db.transaction() as session:
        rows = (
            await session.execute(
                select(bar.c.session_date, bar.c.close, bar.c.volume)
                .select_from(instrument.join(bar, bar.c.instrument_id == instrument.c.id))
                .where(instrument.c.symbol == symbol)
            )
        ).all()
    stored = {r.session_date.isoformat(): (r.close, r.volume) for r in rows}
    for record in corpus[symbol]:
        close, volume = stored[record["date"]]
        assert Decimal(close) == record["close"], f"{symbol} {record['date']}: close changed"
        assert Decimal(volume) == record["volume"], f"{symbol} {record['date']}: volume changed"


async def test_stored_sessions_are_exactly_the_exchange_calendar(
    db: Database, first_run: RunOutcome, corpus: dict[str, Records], window: tuple[date, date]
) -> None:
    expected = {d.isoformat() for d in calendars.sessions("XNYS", *window)}
    async with db.transaction() as session:
        rows = (
            await session.execute(
                select(instrument.c.symbol, bar.c.session_date)
                .select_from(instrument.join(bar, bar.c.instrument_id == instrument.c.id))
                .where(instrument.c.symbol.in_(SYMBOLS))
            )
        ).all()
    by_symbol: dict[str, set[str]] = {}
    for symbol, day in rows:
        by_symbol.setdefault(symbol, set()).add(day.isoformat())
    for symbol, days in by_symbol.items():
        first = min(r["date"] for r in corpus[symbol])
        wanted = {d for d in expected if d >= first}
        assert days <= expected, f"{symbol}: bars on non trading days"
        assert days == wanted, f"{symbol}: missing {sorted(wanted - days)[:5]}"
    assert await _count(db, data_gap) == 0


@pytest.mark.parametrize("symbol", SYMBOLS)
async def test_returns_are_stored_and_equal_an_independent_computation(
    db: Database, first_run: RunOutcome, symbol: str
) -> None:
    async with db.transaction() as session:
        prices = (
            await session.execute(
                select(bar.c.adj_close, bar.c.close)
                .select_from(instrument.join(bar, bar.c.instrument_id == instrument.c.id))
                .where(instrument.c.symbol == symbol)
                .order_by(bar.c.session_date)
            )
        ).all()
        stored = (
            await session.execute(
                select(return_series.c.adj_log_return)
                .select_from(
                    instrument.join(
                        return_series, return_series.c.instrument_id == instrument.c.id
                    )
                )
                .where(instrument.c.symbol == symbol)
                .order_by(return_series.c.session_date)
            )
        ).all()
    assert len(stored) == len(prices)
    expected = np.diff(np.log(np.array([float(r.adj_close or r.close) for r in prices])))
    actual = np.array([float(r.adj_log_return) for r in stored[1:]])
    assert np.allclose(actual, expected, atol=1e-11)


async def test_splits_and_dividends_are_recorded_once(
    db: Database, first_run: RunOutcome, corpus: dict[str, Records]
) -> None:
    async with db.transaction() as session:
        rows = (
            await session.execute(
                select(
                    instrument.c.symbol,
                    corporate_action.c.session_date,
                    corporate_action.c.split_factor,
                    corporate_action.c.dividend,
                ).select_from(
                    instrument.join(
                        corporate_action, corporate_action.c.instrument_id == instrument.c.id
                    )
                )
            )
        ).all()
    for symbol in SYMBOLS:
        mine = [r for r in rows if r.symbol == symbol]
        expected = {
            date.fromisoformat(r["date"])
            for r in corpus[symbol]
            if r["split_factor"] != 1 or r["dividend"] > 0
        }
        assert {r.session_date for r in mine} == expected, f"{symbol}: actions differ"
        assert len(mine) == len(expected), f"{symbol}: an action is stored twice"
        splits = {r.session_date for r in mine if r.split_factor != 1}
        assert splits == SPLITS.get(symbol, set()), f"{symbol}: splits {sorted(splits)}"


async def test_running_the_same_window_again_changes_nothing(
    db: Database, first_run: RunOutcome, corpus: dict[str, Records], window: tuple[date, date]
) -> None:
    tables = (bar, rejected_bar, return_series, corporate_action, outbox)
    before = [await _count(db, t) for t in tables]
    second = await _run(db, RecordedSource(corpus), window)
    assert second.status == "succeeded", second.error
    assert [await _count(db, t) for t in tables] == before
    assert second.run_id != first_run.run_id
