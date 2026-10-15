"""The cleaning gate on years of real vendor bars (FR-MKT-011, NFR-INT-001).

Unit tests prove each rule on constructed bars. These prove the gate on what the vendor
really sends: that it accepts good data, handles real corporate actions, and is
deterministic. They are expected to find nothing wrong with the recorded history; if one
fails, either the code or the vendor's data changed and that is worth knowing.
"""

import copy
import random
from collections import Counter
from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from qs_market import calendars, cleaning

from .conftest import CALENDAR, Records

pytestmark = pytest.mark.realdata

# Real corporate actions (split-for-one factors) the recorded history must contain
KNOWN_SPLITS = {
    ("NVDA", "2021-07-20"): Decimal(4),
    ("NVDA", "2024-06-10"): Decimal(10),
    ("TSLA", "2020-08-31"): Decimal(5),
    ("TSLA", "2022-08-25"): Decimal(3),
    ("AAPL", "2020-08-31"): Decimal(4),
}


def test_vendor_rows_match_the_exchange_calendar(
    corpus: dict[str, Records], window: tuple[date, date], symbol: str
) -> None:
    expected = set(calendars.sessions(CALENDAR, *window))
    received = [date.fromisoformat(r["date"]) for r in corpus[symbol]]
    assert len(received) == len(set(received)), "the vendor sent the same session twice"
    missing, unexpected = expected - set(received), set(received) - expected
    assert not missing and not unexpected, (
        f"{symbol}: {len(missing)} sessions missing, {len(unexpected)} not on the calendar"
    )


def test_vendor_data_is_internally_consistent(corpus: dict[str, Records], symbol: str) -> None:
    """Checked directly on the vendor's numbers, without the gate."""
    broken = [
        r["date"]
        for r in corpus[symbol]
        if not (
            min(r["open"], r["high"], r["low"], r["close"]) > 0
            and r["low"] <= r["open"] <= r["high"]
            and r["low"] <= r["close"] <= r["high"]
            and r["volume"] >= 0
            and r["split_factor"] > 0
            and r["dividend"] >= 0
        )
    ]
    assert not broken, f"{symbol}: inconsistent vendor rows {broken[:5]}"


def test_every_record_is_accounted_for(
    corpus: dict[str, Records], gated: dict[str, cleaning.GateResult], symbol: str
) -> None:
    result, report = gated[symbol], gated[symbol].report
    assert report["received"] == len(corpus[symbol])
    assert len(result.clean) + len(result.rejected) == report["received"]
    assert report["ruleset_version"] == cleaning.RULESET_VERSION


def test_real_history_passes_with_no_rejects_and_no_gaps(
    gated: dict[str, cleaning.GateResult], symbol: str
) -> None:
    result = gated[symbol]
    why = Counter(rule for rej in result.rejected for rule in rej.rules)
    assert not result.rejected, f"{symbol} rejected {dict(why)}, first {result.rejected[0]}"
    assert not result.gaps, f"{symbol} has gaps {[d.isoformat() for d in result.gaps[:5]]}"


def test_known_splits_are_read_correctly_and_never_flagged(
    corpus: dict[str, Records], gated: dict[str, cleaning.GateResult], symbol: str
) -> None:
    by_date = {b.session_date.isoformat(): b for b in gated[symbol].clean}
    for (name, day), factor in KNOWN_SPLITS.items():
        if name != symbol:
            continue
        assert day in by_date, f"{symbol} {day} was not published"
        assert by_date[day].split_factor == factor, f"{symbol} {day} split factor"
        assert "outlier" not in by_date[day].flags, f"{symbol} {day} split flagged as outlier"
    flagged = [b.session_date.isoformat() for b in gated[symbol].clean if "outlier" in b.flags]
    splits = {r["date"] for r in corpus[symbol] if r["split_factor"] != 1}
    assert not set(flagged) & splits, f"{symbol}: split days flagged {set(flagged) & splits}"


def test_dividends_are_carried_through(corpus: dict[str, Records], gated: Any) -> None:
    """KO pays a dividend every quarter; none of them may be lost on the way."""
    paid = {r["date"]: r["dividend"] for r in corpus["KO"] if r["dividend"] > 0}
    published = {
        b.session_date.isoformat(): b.dividend for b in gated["KO"].clean if b.dividend > 0
    }
    assert len(paid) >= 40, f"expected about 11 years of dividends, found {len(paid)}"
    assert paid == published


def test_prices_keep_the_precision_the_database_stores(
    gated: dict[str, cleaning.GateResult], symbol: str
) -> None:
    for bar in gated[symbol].clean:
        assert bar.close == bar.close.quantize(Decimal("0.00000001"))
        assert bar.adj_close is not None
        assert bar.adj_close == bar.adj_close.quantize(Decimal("0.0000000001"))
        assert 0 < bar.close < Decimal(10) ** 15


def test_the_gate_is_deterministic_and_order_independent(
    corpus: dict[str, Records], gated: dict[str, cleaning.GateResult], run_gate: Any, symbol: str
) -> None:
    expected = {(b.session_date, b.content_hash) for b in gated[symbol].clean}
    again = {(b.session_date, b.content_hash) for b in run_gate(corpus[symbol]).clean}
    assert again == expected, "the same input gave a different result"
    shuffled = copy.deepcopy(corpus[symbol])
    random.Random(7).shuffle(shuffled)  # noqa: S311 - a reproducible shuffle, not security
    mixed = {(b.session_date, b.content_hash) for b in run_gate(shuffled).clean}
    assert mixed == expected, "the input order changed the result"
