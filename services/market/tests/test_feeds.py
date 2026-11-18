"""The replay tick core (ADR 01, ADR 08, B-FR-01, B-FR-02): ordering, gap-free seq, the fingerprint
and the rule about adjusted prices, on constructed bars. No database."""

import random
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest

from qs_market import feeds
from qs_market.feeds import BarRow, MissingAdjustedPrices

from .contract_support import tick_problems

ENV = uuid.UUID("6f1c2a4e-3b8d-4f7a-9c21-0a5e7d9b1c01")
IDS = {s: uuid.uuid5(uuid.NAMESPACE_DNS, s) for s in ("AAPL", "MSFT", "KO")}


def bar(symbol: str, day: date, close: str = "100", revision: int = 1, **override: Any) -> BarRow:
    values: dict[str, Any] = {
        "instrument_id": IDS[symbol],
        "symbol": symbol,
        "session_date": day,
        "ts": datetime(day.year, day.month, day.day, 21, 0, tzinfo=UTC),
        "revision": revision,
        "adj_open": Decimal(close) - 1,
        "adj_high": Decimal(close) + 1,
        "adj_low": Decimal(close) - 2,
        "adj_close": Decimal(close),
        "adj_volume": Decimal("1000"),
    }
    values.update(override)
    return BarRow(**values)


def rows() -> list[BarRow]:
    days = [date(2020, 1, 2), date(2020, 1, 3), date(2020, 1, 6)]
    return [bar(s, d, str(100 + i + j)) for i, d in enumerate(days) for j, s in enumerate(IDS)]


def fp(data: list[BarRow]) -> str:
    return feeds.fingerprint(data)


def test_ticks_are_ordered_by_session_then_symbol_with_a_gap_free_seq() -> None:
    ticks = feeds.build_ticks(rows(), env_id=ENV, source_fingerprint="x")
    assert [t["seq"] for t in ticks] == list(range(1, 10))
    assert [(t["session"], t["symbol"]) for t in ticks] == [
        (0, "AAPL"), (0, "KO"), (0, "MSFT"),
        (1, "AAPL"), (1, "KO"), (1, "MSFT"),
        (2, "AAPL"), (2, "KO"), (2, "MSFT"),
    ]  # fmt: skip


def test_the_same_bars_in_any_order_give_the_same_ticks_and_fingerprint() -> None:
    data = rows()
    shuffled = data[:]
    random.Random(7).shuffle(shuffled)  # noqa: S311 - a fixed shuffle for a test, not security
    assert feeds.build_ticks(shuffled, env_id=ENV, source_fingerprint="x") == feeds.build_ticks(
        data, env_id=ENV, source_fingerprint="x"
    )
    assert fp(shuffled) == fp(data)


def test_every_tick_follows_the_contract() -> None:
    for tick in feeds.build_ticks(rows(), env_id=ENV, source_fingerprint=fp(rows())):
        assert tick_problems(tick) == [], tick


def test_decimals_read_the_same_whatever_scale_they_came_in() -> None:
    a = feeds.build_ticks(
        [bar("AAPL", date(2020, 1, 2), "24.17")], env_id=ENV, source_fingerprint="x"
    )
    b = feeds.build_ticks(
        [bar("AAPL", date(2020, 1, 2), "24.1700000000", adj_volume=Decimal("1000.00000000"))],
        env_id=ENV,
        source_fingerprint="x",
    )
    assert a == b
    assert a[0]["close"] == "24.1700000000" and a[0]["volume"] == "1000.00000000"


def test_the_timestamp_is_the_session_close_in_utc() -> None:
    [tick] = feeds.build_ticks([bar("AAPL", date(2020, 1, 2))], env_id=ENV, source_fingerprint="x")
    assert tick["ts"] == "2020-01-02T21:00:00Z"
    assert tick["env_type"] == "replay" and tick["path_index"] is None and tick["scenario"] is None


def test_a_symbol_with_no_bar_on_a_session_has_no_tick_and_seq_stays_gap_free() -> None:
    data = [r for r in rows() if not (r.symbol == "KO" and r.session_date == date(2020, 1, 3))]
    ticks = feeds.build_ticks(data, env_id=ENV, source_fingerprint="x")
    assert [t["seq"] for t in ticks] == list(range(1, 9))
    assert [t["symbol"] for t in ticks if t["session"] == 1] == ["AAPL", "MSFT"]
    assert max(t["session"] for t in ticks) == 2  # the session index is not disturbed


def test_the_fingerprint_changes_when_a_revision_lands() -> None:
    data = rows()
    revised = [bar("AAPL", date(2020, 1, 2), "100", revision=2), *data[1:]]
    assert fp(revised) != fp(data)


def test_the_fingerprint_changes_when_the_vendor_restates_an_adjusted_price() -> None:
    # no revision number changes: the vendor restated the adjusted close after a dividend
    data = rows()
    restated = [bar("AAPL", date(2020, 1, 2), "99.4900000000"), *data[1:]]
    assert restated[0].revision == data[0].revision
    assert fp(restated) != fp(data)
    first = feeds.build_ticks(data, env_id=ENV, source_fingerprint=fp(data))[0]
    again = feeds.build_ticks(restated, env_id=ENV, source_fingerprint=fp(restated))[0]
    assert first["close"] != again["close"]  # the served price moved with it


def test_the_fingerprint_changes_when_a_bar_is_added_or_removed() -> None:
    data = rows()
    assert fp(data[:-1]) != fp(data)
    assert fp([*data, bar("AAPL", date(2020, 1, 7))]) != fp(data)


def test_a_fingerprint_of_blocks_equals_the_fingerprint_of_lines() -> None:
    # the replay service gets one text per session from the database; the bytes hashed are the same
    lines = [feeds.canonical_line(r) for r in feeds.ordered(rows())]
    by_session = [
        "\n".join(feeds.canonical_line(r) for r in feeds.ordered(rows()) if r.session_date == day)
        for day in sorted({r.session_date for r in rows()})
    ]
    assert feeds.fingerprint_of_blocks(by_session) == feeds.fingerprint_of_lines(lines)
    assert feeds.fingerprint_of_blocks(by_session) == fp(rows())


def test_the_fingerprint_names_its_algorithm_and_is_stable() -> None:
    value = fp(rows())
    assert value.startswith("xxh3:") and len(value) == len("xxh3:") + 32
    assert fp(rows()) == value


@pytest.mark.parametrize("missing", ["adj_open", "adj_high", "adj_low", "adj_close", "adj_volume"])
def test_a_bar_without_an_adjusted_value_refuses_the_whole_environment(missing: str) -> None:
    gap: dict[str, Any] = {missing: None}
    data = [*rows(), bar("KO", date(2020, 1, 7), **gap), bar("KO", date(2020, 1, 8), **gap)]
    with pytest.raises(MissingAdjustedPrices) as caught:
        feeds.build_ticks(data, env_id=ENV, source_fingerprint="x")
    assert caught.value.missing == {"KO": 2}
    assert "KO (2)" in str(caught.value)
    with pytest.raises(MissingAdjustedPrices):
        fp(data)
    assert feeds.missing_adjusted(rows()) == {}


def test_paging_by_after_seq_covers_every_tick_once() -> None:
    ticks = feeds.build_ticks(rows(), env_id=ENV, source_fingerprint="x")
    seen: list[int] = []
    cursor: int | None = 0
    while cursor is not None:
        items, cursor = feeds.page(ticks, cursor, 4)
        seen += [t["seq"] for t in items]
    assert seen == list(range(1, 10))


def test_the_last_page_has_no_next_cursor_and_a_cursor_past_the_end_is_empty() -> None:
    ticks = feeds.build_ticks(rows(), env_id=ENV, source_fingerprint="x")
    items, cursor = feeds.page(ticks, 5, 4)
    assert [t["seq"] for t in items] == [6, 7, 8, 9] and cursor is None
    assert feeds.page(ticks, 9, 4) == ([], None)
    assert feeds.page(ticks, 0, 9)[1] is None  # exactly one full page is also the last
