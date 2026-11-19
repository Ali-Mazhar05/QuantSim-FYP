"""Trading calendar helpers: sessions, closes in UTC, sessions before a date."""

from datetime import UTC, date, datetime, timedelta

from qs_market import calendars

CAL = "XNYS"


def test_sessions_skip_weekends_and_holidays() -> None:
    # 2025-11-27 is Thanksgiving; 2025-11-29/30 is a weekend
    assert calendars.sessions(CAL, date(2025, 11, 26), date(2025, 12, 1)) == [
        date(2025, 11, 26),
        date(2025, 11, 28),
        date(2025, 12, 1),
    ]
    assert not calendars.is_session(CAL, date(2025, 11, 27))
    assert calendars.is_session(CAL, date(2025, 11, 28))


def test_session_close_follows_daylight_saving_and_early_closes() -> None:
    assert calendars.session_close(CAL, date(2025, 10, 31)) == datetime(
        2025, 10, 31, 20, tzinfo=UTC
    )
    assert calendars.session_close(CAL, date(2025, 11, 3)) == datetime(2025, 11, 3, 21, tzinfo=UTC)
    assert calendars.session_close(CAL, date(2025, 11, 28)) == datetime(
        2025, 11, 28, 18, tzinfo=UTC
    )


def test_sessions_before_counts_trading_days_only() -> None:
    # Five sessions before Monday 2025-12-01: 11-21, 11-24, 11-25, 11-26, 11-28
    assert calendars.sessions_before(CAL, date(2025, 12, 1), 5) == date(2025, 11, 21)
    assert calendars.sessions_before(CAL, date(2025, 12, 1), 0) == date(2025, 12, 1)


def test_closed_sessions_wait_for_the_grace_period() -> None:
    friday_close = datetime(2025, 10, 31, 20, tzinfo=UTC)
    grace = timedelta(hours=12)
    window = (date(2025, 10, 30), date(2025, 10, 31))
    assert calendars.closed_sessions(CAL, *window, as_of=friday_close, grace=grace) == [
        date(2025, 10, 30)
    ]
    assert calendars.closed_sessions(CAL, *window, as_of=friday_close + grace, grace=grace) == [
        date(2025, 10, 30),
        date(2025, 10, 31),
    ]


def test_dates_outside_the_calendar_range_are_not_sessions() -> None:
    assert calendars.sessions(CAL, date(1800, 1, 1), date(1800, 12, 31)) == []
    assert not calendars.is_session(CAL, date(1800, 1, 2))
