"""The NYSE sessions a synthetic run's steps stand on (DL-019, DL-042).

Step 0 is the first session after the day the run's start prices describe, and every later step is
the next session, so a synthetic tick is dated like a replay tick: by the real close in UTC (it
moves with daylight saving and early closes). The calendar is extended past today because a run may
reach years ahead; exchange_calendars knows the holiday rules, not future one-off closures.
"""

from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from typing import Any

import exchange_calendars as xcals
import pandas as pd

CALENDAR_END = date(
    2045, 12, 31
)  # beyond the longest run (2,520 sessions) from any plausible start


@lru_cache(maxsize=1)
def _calendar() -> Any:
    return xcals.get_calendar("XNYS", end=pd.Timestamp(CALENDAR_END))


@lru_cache(maxsize=64)
def step_closes(after: date, n_steps: int) -> tuple[datetime, ...]:
    """The closes, in UTC, of the ``n_steps`` sessions after ``after`` (which need not be one)."""
    calendar = _calendar()
    # about 1.5 calendar days per session covers weekends and holidays; the slack is generous
    last = min(after + timedelta(days=n_steps * 2 + 30), CALENDAR_END)
    sessions = calendar.sessions_in_range(
        pd.Timestamp(after + timedelta(days=1)), pd.Timestamp(last)
    )
    if len(sessions) < n_steps:
        raise ValueError("the calendar does not reach far enough for this run")
    return tuple(
        calendar.session_close(session).to_pydatetime().astimezone(UTC)
        for session in sessions[:n_steps]
    )
