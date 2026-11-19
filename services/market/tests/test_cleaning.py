"""The cleaning gate (PRD FR-25, FR-26; SPEC FR-MKT-011): one test per rule, the
duplicate and outlier cases, UTC timestamps across daylight saving and an early close,
gaps, and properties that must hold for any input."""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from qs_market.cleaning import RULESET_VERSION, GateResult, run_gate

CAL = "XNYS"
# Mon 2025-10-27 .. Fri 2025-10-31 are sessions; 2025-11-01/02 are a weekend
START, END = date(2025, 10, 27), date(2025, 10, 31)
LATER = datetime(2025, 12, 1, tzinfo=UTC)  # every session in the window has closed


def bar(day: str, **overrides: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "date": f"{day}T00:00:00.000Z",
        "open": 100,
        "high": 105,
        "low": 95,
        "close": 101,
        "volume": 1_000_000,
        "adj_open": 100,
        "adj_high": 105,
        "adj_low": 95,
        "adj_close": 101,
        "adj_volume": 1_000_000,
        "split_factor": 1,
        "dividend": 0,
    }
    record.update(overrides)
    return record


def week(**overrides_by_day: dict[str, Any]) -> list[dict[str, Any]]:
    days = ["2025-10-27", "2025-10-28", "2025-10-29", "2025-10-30", "2025-10-31"]
    return [bar(d, **overrides_by_day.get(d.replace("-", "_"), {})) for d in days]


def gate(records: list[dict[str, Any]], **kwargs: Any) -> GateResult:
    options: dict[str, Any] = {
        "calendar": CAL,
        "window_start": START,
        "window_end": END,
        "as_of": LATER,
        "previous_close": None,
        "outlier_log_return": 0.405,
    }
    options.update(kwargs)
    return run_gate(records, **options)


def test_a_clean_week_passes_untouched() -> None:
    result = gate(week())
    assert [b.session_date for b in result.clean] == [date(2025, 10, d) for d in range(27, 32)]
    assert result.rejected == [] and result.gaps == []
    assert result.report["passed_untouched"] == 5
    assert result.report["ruleset_version"] == RULESET_VERSION


@pytest.mark.parametrize(
    ("record", "rule"),
    [
        ({"date": "2025-10-28", "open": None}, "malformed"),
        ({"date": "not a date"}, "malformed"),
        ({"date": "2025-10-28", "close": "abc"}, "malformed"),
        # What the database would refuse must never get past the gate
        ({"date": "2025-10-28", "split_factor": 0}, "malformed"),
        ({"date": "2025-10-28", "split_factor": -2}, "malformed"),
        ({"date": "2025-10-28", "dividend": -0.5}, "malformed"),
        ({"date": "2025-10-28", "high": 10**15, "close": 10**15 - 1}, "malformed"),
        ({"date": "2025-10-28", "volume": 10**20}, "malformed"),
        ({"date": "2025-10-28", "adj_close": 10**15}, "malformed"),
        ({"date": "2025-10-24"}, "outside_window"),
        ({"date": "2025-11-01"}, "non_trading_day"),
        ({"date": "2025-10-28", "low": 0}, "non_positive_price"),
        ({"date": "2025-10-28", "close": -3}, "non_positive_price"),
        ({"date": "2025-10-28", "adj_close": 0}, "non_positive_price"),
        ({"date": "2025-10-28", "low": 106}, "ohlc_order"),
        ({"date": "2025-10-28", "close": 110}, "ohlc_order"),
        ({"date": "2025-10-28", "open": 90}, "ohlc_order"),
        ({"date": "2025-10-28", "volume": -1}, "negative_volume"),
    ],
)
def test_each_reject_rule(record: dict[str, Any], rule: str) -> None:
    day = record.pop("date")
    result = gate([bar(day, **record)], window_end=date(2025, 11, 2))
    assert len(result.rejected) == 1
    assert rule in result.rejected[0].rules
    assert result.clean == []
    assert result.report["by_rule"][rule] == 1


def test_a_record_breaking_several_rules_lists_every_rule() -> None:
    result = gate([bar("2025-11-01", volume=-1, low=0)], window_end=date(2025, 11, 2))
    assert set(result.rejected[0].rules) == {
        "non_trading_day",
        "non_positive_price",
        "negative_volume",
    }


def test_identical_duplicates_keep_one_copy_and_count_as_corrected() -> None:
    records = [*week(), bar("2025-10-29")]
    result = gate(records)
    assert len(result.clean) == 5
    assert result.report["duplicates_removed"] == 1
    assert result.report["corrected"] == 1
    assert result.report["passed_untouched"] == 4


def test_conflicting_duplicates_reject_every_copy_and_leave_a_gap() -> None:
    records = [*week(), bar("2025-10-29", close=102)]
    result = gate(records)
    assert [r.rules for r in result.rejected] == [("duplicate_conflict",)] * 2
    assert date(2025, 10, 29) not in {b.session_date for b in result.clean}
    assert result.gaps == [date(2025, 10, 29)]


def test_zero_volume_is_published_with_a_flag() -> None:
    result = gate(week(**{"2025_10_28": {"volume": 0, "adj_volume": 0}}))
    flagged = {b.session_date: b.flags for b in result.clean}
    assert flagged[date(2025, 10, 28)] == ("zero_volume",)
    assert result.report["flagged"] == {"zero_volume": 1}


def jump(day: str, close: float, **extra: Any) -> dict[str, Any]:
    return bar(
        day,
        open=close,
        high=close,
        low=close,
        close=close,
        adj_open=close,
        adj_high=close,
        adj_low=close,
        adj_close=close,
        **extra,
    )


def test_a_60_percent_jump_is_flagged_as_an_outlier() -> None:
    records = [bar("2025-10-27"), jump("2025-10-28", 161.6)]
    result = gate(records, window_end=date(2025, 10, 28))
    assert result.clean[1].flags == ("outlier",)


def test_outlier_policy_reject_rejects_the_jump() -> None:
    records = [bar("2025-10-27"), jump("2025-10-28", 161.6)]
    result = gate(records, window_end=date(2025, 10, 28), outlier_policy="reject")
    assert [r.rules for r in result.rejected] == [("outlier",)]
    assert result.report["passed_untouched"] == 1


def test_the_outlier_check_is_skipped_on_a_split_day() -> None:
    records = [bar("2025-10-27"), jump("2025-10-28", 50.5, split_factor=2)]
    result = gate(records, window_end=date(2025, 10, 28))
    assert result.clean[1].flags == ()


def test_the_outlier_check_uses_the_last_stored_close_across_runs() -> None:
    result = gate(
        [jump("2025-10-27", 30)], window_end=date(2025, 10, 27), previous_close=Decimal("101")
    )
    assert result.clean[0].flags == ("outlier",)


def test_timestamps_are_the_actual_session_close_in_utc() -> None:
    # US daylight saving ends on 2025-11-02; 2025-11-28 closes early at 13:00 New York
    records = [bar("2025-10-31"), bar("2025-11-03"), bar("2025-11-28")]
    result = gate(records, window_start=date(2025, 10, 31), window_end=date(2025, 11, 28))
    closes = {b.session_date: b.ts for b in result.clean}
    assert closes[date(2025, 10, 31)] == datetime(2025, 10, 31, 20, 0, tzinfo=UTC)
    assert closes[date(2025, 11, 3)] == datetime(2025, 11, 3, 21, 0, tzinfo=UTC)
    assert closes[date(2025, 11, 28)] == datetime(2025, 11, 28, 18, 0, tzinfo=UTC)


def test_a_missing_session_is_a_gap_but_a_holiday_never_is() -> None:
    # 2025-11-27 is Thanksgiving: no session, so never a gap
    records = [bar("2025-11-24"), bar("2025-11-26"), bar("2025-11-28")]
    result = gate(records, window_start=date(2025, 11, 24), window_end=date(2025, 11, 28))
    assert result.gaps == [date(2025, 11, 25)]


def test_a_session_is_not_a_gap_until_its_close_plus_12_hours_has_passed() -> None:
    # Friday 2025-10-31 closes 20:00 UTC; it may be judged missing from 08:00 UTC Saturday
    records = week()[:4]
    early = gate(records, as_of=datetime(2025, 11, 1, 7, 59, tzinfo=UTC))
    late = gate(records, as_of=datetime(2025, 11, 1, 8, 0, tzinfo=UTC))
    assert early.gaps == []
    assert late.gaps == [date(2025, 10, 31)]


def test_prices_keep_8_decimal_places() -> None:
    result = gate([bar("2025-10-28", close="101.123456789")], window_end=date(2025, 10, 28))
    assert result.clean[0].close == Decimal("101.12345679")


def test_adjusted_prices_keep_the_10_decimal_places_the_vendor_sends() -> None:
    result = gate([bar("2025-10-28", adj_close="183.4133636527")], window_end=date(2025, 10, 28))
    assert result.clean[0].adj_close == Decimal("183.4133636527")


def test_identical_content_gives_an_identical_hash() -> None:
    first, second = gate(week()), gate(week())
    assert [b.content_hash for b in first.clean] == [b.content_hash for b in second.clean]
    changed = gate(week(**{"2025_10_29": {"close": 102}}))
    assert first.clean[2].content_hash != changed.clean[2].content_hash


def test_a_restated_adjusted_price_does_not_change_the_hash() -> None:
    # The vendor rewrites adjusted prices backwards at every dividend or split; that must
    # not look like a correction of the bar
    original = gate(week())
    restated = gate(
        week(
            **{
                "2025_10_29": {
                    "adj_open": 99.9,
                    "adj_high": 104.9,
                    "adj_low": 94.9,
                    "adj_close": 100.9,
                    "adj_volume": 1_000_001,
                }
            }
        )
    )
    assert [b.content_hash for b in original.clean] == [b.content_hash for b in restated.clean]
    assert restated.clean[2].adj_close == Decimal("100.9000000000")


@pytest.mark.parametrize(
    "change",
    [
        {"open": 100.5},
        {"high": 106},
        {"low": 94},
        {"close": 100},
        {"volume": 999_999},
        {"split_factor": 2},
        {"dividend": 0.25},
    ],
)
def test_a_change_to_any_raw_vendor_value_changes_the_hash(change: dict[str, Any]) -> None:
    original = gate(week())
    changed = gate(week(**{"2025_10_29": change}))
    assert original.clean[2].content_hash != changed.clean[2].content_hash


# --- properties: for any input whatsoever ----------------------------------------------

number = st.one_of(
    st.none(),
    st.integers(min_value=-5, max_value=500),
    st.decimals(min_value=-5, max_value=500, places=10, allow_nan=False),
    st.sampled_from(["abc", "", "1e3", "NaN", "Infinity"]),
)
day = st.dates(min_value=date(2025, 10, 20), max_value=date(2025, 11, 9)).map(str)
record = st.fixed_dictionaries(
    {"date": st.one_of(day, st.just("garbage"))},
    optional={
        "open": number,
        "high": number,
        "low": number,
        "close": number,
        "volume": number,
        "adj_close": number,
        "split_factor": st.sampled_from([1, 2, 0.5]),
    },
)


@settings(max_examples=300, deadline=None)
@given(st.lists(record, max_size=30))
def test_the_gate_never_publishes_an_impossible_bar_and_the_report_adds_up(
    records: list[dict[str, Any]],
) -> None:
    result = gate(records, window_start=date(2025, 10, 20), window_end=date(2025, 11, 9))
    for b in result.clean:
        assert min(b.open, b.high, b.low, b.close) > 0
        assert b.low <= b.high
        assert b.low <= b.open <= b.high and b.low <= b.close <= b.high
        assert b.volume >= 0
    report = result.report
    assert report["received"] == len(records)
    assert report["received"] == (
        report["passed_untouched"]
        + report["corrected"]
        + report["duplicates_removed"]
        + report["rejected"]
    )
    assert len({b.session_date for b in result.clean}) == len(result.clean)
