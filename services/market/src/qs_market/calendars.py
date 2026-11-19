"""Trading calendars (FR-MKT-011: align timestamps to UTC against the instrument's
trading calendar).

A daily bar belongs to a *session*; its timestamp is that session's actual close in UTC,
which moves with daylight saving and early closes. Holidays and weekends are not
sessions, so they are never reported as missing bars.
"""

from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from typing import Any

import exchange_calendars as xcals
import pandas as pd


@lru_cache(maxsize=16)
def _calendar(code: str) -> Any:
    return xcals.get_calendar(code)


def _clamp(code: str, start: date, end: date) -> tuple[date, date] | None:
    calendar = _calendar(code)
    first = calendar.first_session.date()
    last = calendar.last_session.date()
    start, end = max(start, first), min(end, last)
    return (start, end) if start <= end else None


def sessions(code: str, start: date, end: date) -> list[date]:
    """Every trading session from ``start`` to ``end``, both inclusive."""
    bounds = _clamp(code, start, end)
    if bounds is None:
        return []
    index = _calendar(code).sessions_in_range(pd.Timestamp(bounds[0]), pd.Timestamp(bounds[1]))
    return [ts.date() for ts in index]


def is_session(code: str, day: date) -> bool:
    bounds = _clamp(code, day, day)
    return bounds is not None and bool(_calendar(code).is_session(pd.Timestamp(day)))


def session_close(code: str, day: date) -> datetime:
    """The UTC instant the session on ``day`` closes (handles DST and early closes)."""
    close = _calendar(code).session_close(pd.Timestamp(day))
    result: datetime = close.to_pydatetime()
    return result.astimezone(UTC)


def sessions_before(code: str, day: date, count: int) -> date:
    """The session ``count`` sessions before ``day`` (``day`` itself when count is 0)."""
    if count <= 0:
        return day
    # Generous span: about 1.6 calendar days per session covers weekends and holidays
    window = sessions(code, day - timedelta(days=count * 2 + 10), day - timedelta(days=1))
    return window[-count] if len(window) >= count else (window[0] if window else day)


def closed_sessions(
    code: str, start: date, end: date, *, as_of: datetime, grace: timedelta
) -> list[date]:
    """Sessions in the window whose close plus ``grace`` (vendor publication delay) is
    already past at ``as_of``: the bars a vendor should have by now."""
    return [s for s in sessions(code, start, end) if session_close(code, s) + grace <= as_of]
