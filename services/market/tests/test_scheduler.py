"""Scheduler due logic (pure, no sleeping) and what enqueueing does to the queue."""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any

import pytest
from pydantic import SecretStr, ValidationError
from sqlalchemy import select, text

from qs_market.models import ingestion_run
from qs_market.pipeline.scheduler import (
    DueRun,
    Slot,
    due_runs,
    enqueue,
    parse_hhmm,
    run_scheduler,
    slots,
)
from qs_market.settings import MarketSettings
from qs_template import Database

UNREACHABLE_DB = SecretStr("postgresql+asyncpg://x:x@127.0.0.1:1/x")


def settings(**values: Any) -> MarketSettings:
    return MarketSettings(
        database_url=UNREACHABLE_DB, redis_url=SecretStr("redis://unused"), **values
    )


SCHEDULE = slots(settings())


def at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=UTC)


def modes(runs: list[DueRun]) -> dict[str, date]:
    return {r.mode: r.day for r in runs}


def test_defaults_are_22_30_and_09_30_utc() -> None:
    assert [(s.mode, s.at.hour, s.at.minute) for s in SCHEDULE] == [
        ("daily", 22, 30),
        ("catchup", 9, 30),
    ]


def test_nothing_is_due_before_the_next_slot_once_both_were_handled() -> None:
    handled = {"daily": date(2026, 10, 13), "catchup": date(2026, 10, 14)}
    assert due_runs(at(14, 22, 29), handled, SCHEDULE) == []


def test_catchup_is_due_at_09_30_and_not_the_daily() -> None:
    handled = {"daily": date(2026, 10, 13), "catchup": date(2026, 10, 13)}
    assert due_runs(at(14, 9, 29), handled, SCHEDULE) == []
    due = due_runs(at(14, 9, 30), handled, SCHEDULE)
    assert modes(due) == {"catchup": date(2026, 10, 14)}
    assert due[0].idempotency_key == "catchup:2026-10-14"


def test_daily_is_due_at_22_30_with_that_days_key() -> None:
    handled = {"daily": date(2026, 10, 13), "catchup": date(2026, 10, 14)}
    assert due_runs(at(14, 22, 29), handled, SCHEDULE) == []
    due = due_runs(at(14, 22, 30), handled, SCHEDULE)
    assert [r.idempotency_key for r in due] == ["daily:2026-10-14"]


def test_the_same_day_twice_enqueues_once() -> None:
    last: dict[str, date] = {}
    first = due_runs(at(14, 23, 0), last, SCHEDULE)
    assert modes(first) == {"daily": date(2026, 10, 14), "catchup": date(2026, 10, 14)}
    last.update(modes(first))
    assert due_runs(at(14, 23, 30), last, SCHEDULE) == []
    assert due_runs(at(15, 9, 29), last, SCHEDULE) == []


def test_after_downtime_only_the_latest_slot_of_each_mode_is_due() -> None:
    # Down from the 11th to the 14th afternoon: one daily (the 13th) and one catch-up
    # (the 14th), not a backlog of every missed day
    last = {"daily": date(2026, 10, 11), "catchup": date(2026, 10, 11)}
    due = due_runs(at(14, 15, 0), last, SCHEDULE)
    assert modes(due) == {"daily": date(2026, 10, 13), "catchup": date(2026, 10, 14)}


def test_a_window_missed_while_down_is_picked_up_late_the_same_day() -> None:
    last = {"daily": date(2026, 10, 13), "catchup": date(2026, 10, 14)}
    assert due_runs(at(14, 22, 0), last, SCHEDULE) == []
    assert modes(due_runs(at(14, 23, 59), last, SCHEDULE)) == {"daily": date(2026, 10, 14)}


def test_before_the_first_slot_of_the_day_the_previous_one_is_due() -> None:
    due = due_runs(at(14, 0, 5), {}, SCHEDULE)
    assert modes(due) == {"daily": date(2026, 10, 13), "catchup": date(2026, 10, 13)}


def test_a_non_utc_clock_is_converted() -> None:
    karachi = timezone(timedelta(hours=5))
    local = datetime(2026, 10, 14, 14, 30, tzinfo=karachi)  # 09:30 UTC
    handled = {"daily": date(2026, 10, 13), "catchup": date(2026, 10, 13)}
    assert modes(due_runs(local, handled, SCHEDULE)) == {"catchup": date(2026, 10, 14)}


def test_custom_slots() -> None:
    schedule = [Slot("daily", parse_hhmm("01:15"))]
    handled = {"daily": date(2026, 10, 13)}
    assert due_runs(at(14, 1, 14), handled, schedule) == []
    assert modes(due_runs(at(14, 1, 15), handled, schedule)) == {"daily": date(2026, 10, 14)}


def test_scheduler_is_off_by_default_and_times_come_from_settings() -> None:
    default = settings()
    assert default.ingest_scheduler_enabled is False
    assert (default.ingest_daily_time, default.ingest_catchup_time) == ("22:30", "09:30")
    custom = settings(
        ingest_scheduler_enabled=True, ingest_daily_time="21:05", ingest_catchup_time="07:00"
    )
    assert custom.ingest_scheduler_enabled is True
    assert [(s.at.hour, s.at.minute) for s in slots(custom)] == [(21, 5), (7, 0)]


@pytest.mark.parametrize("bad", ["24:00", "9:30", "09:60", "0930", "ab:cd", "", "09:30:00"])
def test_bad_times_are_refused_at_start(bad: str) -> None:
    with pytest.raises(ValidationError, match="HH:MM"):
        settings(ingest_daily_time=bad)
    with pytest.raises(ValidationError, match="HH:MM"):
        settings(ingest_catchup_time=bad)


@pytest.fixture
async def database(migrated_database_url: str) -> AsyncIterator[Database]:
    db = Database(
        MarketSettings(
            database_url=SecretStr(migrated_database_url), redis_url=SecretStr("redis://unused")
        )
    )
    async with db.transaction() as session:
        await session.execute(text("TRUNCATE ingestion_run CASCADE"))
    yield db
    async with db.transaction() as session:
        await session.execute(text("TRUNCATE ingestion_run CASCADE"))
    await db.close()


async def stored_runs(database: Database) -> list[Any]:
    async with database.transaction() as session:
        return list((await session.execute(select(ingestion_run))).all())


async def finish_all(database: Database) -> None:
    async with database.transaction() as session:
        await session.execute(text("UPDATE ingestion_run SET status = 'succeeded'"))


@pytest.mark.db
async def test_enqueue_creates_one_pending_run_per_mode_and_day(database: Database) -> None:
    run = DueRun("daily", date(2026, 10, 14))
    assert await enqueue(database, run, vendor="fixture") == "created"
    # A second scheduler, or a restart, for the same slot creates nothing
    assert await enqueue(database, run, vendor="fixture") == "exists"
    runs = await stored_runs(database)
    assert len(runs) == 1
    row = runs[0]
    assert (row.mode, row.status, row.requested_by) == ("daily", "pending", "scheduler")
    assert row.idempotency_key == "daily:2026-10-14"
    assert row.instrument_ids is None and row.window_start is None
    # The same key stays "exists" after the run finished
    await finish_all(database)
    assert await enqueue(database, run, vendor="fixture") == "exists"
    # The next day and the other mode are new runs
    assert await enqueue(database, DueRun("daily", date(2026, 10, 15)), vendor="fixture") == (
        "created"
    )
    await finish_all(database)
    assert await enqueue(database, DueRun("catchup", date(2026, 10, 14)), vendor="fixture") == (
        "created"
    )
    assert len(await stored_runs(database)) == 3


@pytest.mark.db
async def test_a_run_still_active_blocks_the_next_one_without_losing_the_slot(
    database: Database,
) -> None:
    assert await enqueue(database, DueRun("daily", date(2026, 10, 14)), vendor="fixture") == (
        "created"
    )
    # The daily run has not finished: an all-instrument catch-up would be the same work
    catchup = DueRun("catchup", date(2026, 10, 14))
    assert await enqueue(database, catchup, vendor="fixture") == "active"
    assert len(await stored_runs(database)) == 1
    await finish_all(database)
    assert await enqueue(database, catchup, vendor="fixture") == "created"


@pytest.mark.db
async def test_two_schedulers_at_once_create_one_run_for_the_slot(database: Database) -> None:
    run = DueRun("daily", date(2026, 10, 14))
    results = await asyncio.gather(*(enqueue(database, run, vendor="fixture") for _ in range(6)))
    assert sorted(results) == ["created"] + ["exists"] * 5
    assert len(await stored_runs(database)) == 1


@pytest.mark.db
async def test_the_loop_enqueues_each_slot_once_and_retries_a_blocked_one(
    database: Database,
) -> None:
    stopping = asyncio.Event()
    task = asyncio.create_task(run_scheduler(database, settings(), stopping, tick_seconds=0.05))
    await asyncio.sleep(0.5)  # many ticks
    # The wall clock puts both slots due; the first one queued blocks the second, so one
    # run exists and the blocked slot is retried on every tick without piling up
    first = await stored_runs(database)
    assert len(first) == 1
    await finish_all(database)
    await asyncio.sleep(0.5)
    stopping.set()
    await asyncio.wait_for(task, timeout=5)
    runs = await stored_runs(database)
    assert sorted(r.mode for r in runs) == ["catchup", "daily"]
    assert len({r.idempotency_key for r in runs}) == 2
