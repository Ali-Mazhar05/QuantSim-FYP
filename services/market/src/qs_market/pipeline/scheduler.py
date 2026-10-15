"""The scheduler: enqueues the daily and catch-up runs, nothing else.

``due_runs`` is a pure function of the clock and what this process already enqueued, so
it is tested without sleeping. The idempotency key (mode and UTC date) is what makes two
schedulers, or a restarted one, create one run per mode and day.

After downtime only the latest slot of a mode is enqueued, never a backlog: a run's
window already reaches back five sessions, so one run repairs everything that was missed.
"""

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

from qs_market.pipeline.runs import RunConflict, create_run
from qs_market.settings import MarketSettings
from qs_template import Database
from qs_template.logging import get_logger

TICK_SECONDS = 30.0

log = get_logger(__name__)


@dataclass(frozen=True)
class Slot:
    mode: str  # daily or catchup
    at: time  # UTC


@dataclass(frozen=True)
class DueRun:
    mode: str
    day: date  # the UTC date of the slot

    @property
    def idempotency_key(self) -> str:
        return f"{self.mode}:{self.day.isoformat()}"


def parse_hhmm(value: str) -> time:
    hours, separator, minutes = value.partition(":")
    if not separator or len(hours) != 2 or len(minutes) != 2:
        raise ValueError(f"{value!r} is not a time of day written HH:MM")
    return time(int(hours), int(minutes))


def slots(settings: MarketSettings) -> list[Slot]:
    return [
        Slot("daily", parse_hhmm(settings.ingest_daily_time)),
        Slot("catchup", parse_hhmm(settings.ingest_catchup_time)),
    ]


def due_runs(
    now: datetime, last_enqueued: Mapping[str, date], schedule: list[Slot]
) -> list[DueRun]:
    """The runs whose latest slot has passed and that were not enqueued yet.

    ``last_enqueued`` maps a mode to the slot date already handled by this process.
    """
    now = now.astimezone(UTC)
    due: list[DueRun] = []
    for slot in schedule:
        day = now.date() if now.time() >= slot.at else now.date() - timedelta(days=1)
        handled = last_enqueued.get(slot.mode)
        if handled is None or handled < day:
            due.append(DueRun(slot.mode, day))
    return due


async def enqueue(database: Database, run: DueRun, *, vendor: str) -> str:
    """Create the run. Answers ``created``, ``exists`` (the key already had a run) or
    ``active`` (another run for every instrument is still queued or running; the slot is
    not handled and the next tick tries again)."""
    async with database.transaction() as session:
        try:
            created = await create_run(
                session,
                mode=run.mode,
                window=None,
                instrument_ids=None,
                idempotency_key=run.idempotency_key,
                requested_by="scheduler",
                vendor=vendor,
            )
        except RunConflict as exc:
            log.info("scheduled run skipped, one is active", mode=run.mode, active=str(exc.run_id))
            return "active"
    return "created" if created.created else "exists"


async def run_scheduler(
    database: Database,
    settings: MarketSettings,
    stopping: asyncio.Event,
    *,
    tick_seconds: float = TICK_SECONDS,
) -> None:
    schedule = slots(settings)
    last: dict[str, date] = {}
    while not stopping.is_set():
        try:
            for run in due_runs(datetime.now(UTC), last, schedule):
                outcome = await enqueue(database, run, vendor=settings.vendor)
                if outcome != "active":
                    last[run.mode] = run.day
                    log.info(
                        "scheduled run", mode=run.mode, day=run.day.isoformat(), outcome=outcome
                    )
        except Exception as exc:  # the next tick retries
            log.error("scheduler tick failed", error=str(exc))
        try:
            await asyncio.wait_for(stopping.wait(), timeout=tick_seconds)
        except TimeoutError:
            pass
