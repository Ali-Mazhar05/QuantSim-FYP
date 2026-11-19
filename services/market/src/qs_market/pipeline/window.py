"""Which sessions a run asks the vendor for, per instrument (plan section 5.2 step 1).

An explicit window is honoured as given. Otherwise the window starts five sessions before
the last stored bar, so late vendor corrections are picked up, and ends at the latest
session that has closed. A brand-new instrument starts at the backfill start.
"""

import uuid
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from qs_market import calendars
from qs_market.models import bar

OVERLAP_SESSIONS = 5


def latest_closed_session(calendar: str, as_of: datetime) -> date | None:
    today = as_of.date()
    closed = calendars.closed_sessions(
        calendar, today - timedelta(days=10), today, as_of=as_of, grace=timedelta(0)
    )
    return closed[-1] if closed else None


async def resolve_window(
    session: AsyncSession,
    *,
    calendar: str,
    instrument_id: uuid.UUID,
    run_start: date | None,
    run_end: date | None,
    as_of: datetime,
    backfill_start: date,
) -> tuple[date, date] | None:
    """The window to fetch, or None when it holds no expected session."""
    end = run_end or latest_closed_session(calendar, as_of)
    if end is None:
        return None
    start = run_start
    if start is None:
        last = (
            await session.execute(
                select(func.max(bar.c.session_date)).where(bar.c.instrument_id == instrument_id)
            )
        ).scalar_one()
        start = (
            calendars.sessions_before(calendar, last, OVERLAP_SESSIONS)
            if last is not None
            else backfill_start
        )
    if start > end or not calendars.sessions(calendar, start, end):
        return None
    return start, end
