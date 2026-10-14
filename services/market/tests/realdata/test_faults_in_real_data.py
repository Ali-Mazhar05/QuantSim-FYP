"""Planted faults in real bars: each must be caught by its own rule, and nothing else may
change.

Real data is clean, so it cannot show that the rejection paths work. Constructed bars can
(see test_cleaning.py), but only on made-up numbers. Here one real symbol's real bars
get a fault each, which is the nearest thing to what a bad vendor day would be.
"""

import copy
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest

from .conftest import Records

pytestmark = pytest.mark.realdata

SYMBOL = "AAPL"
# Distinct, quiet sessions well away from the edges of the window. The row removed by
# "missing_session" has the highest index, so the others keep their positions.
AT = {
    "negative_price": 400,
    "low_above_high": 800,
    "weekend_date": 1200,
    "identical_duplicate": 1500,
    "conflicting_duplicate": 1800,
    "price_jump": 2100,
    "zero_volume": 2400,
    "missing_session": 2700,
}

# fault -> (what the gate must do, the rule or flag, does the session lose its bar?)
EXPECTED = {
    "negative_price": ("rejected", "non_positive_price", True),
    "low_above_high": ("rejected", "ohlc_order", True),
    "weekend_date": ("rejected", "non_trading_day", True),
    "conflicting_duplicate": ("rejected", "duplicate_conflict", True),
    "identical_duplicate": ("deduplicated", None, False),
    "price_jump": ("flagged", "outlier", False),
    "zero_volume": ("flagged", "zero_volume", False),
    "missing_session": ("gap", None, True),
}


def apply_fault(work: Records, fault: str, original: Records) -> str:
    """Plant one fault in ``work`` (in place) and return the session it affects."""
    row = work[AT[fault]] if fault != "missing_session" else None
    day = original[AT[fault]]["date"]
    if fault == "negative_price" and row:
        row["open"] = Decimal("-5")
    elif fault == "low_above_high" and row:
        row["low"] = row["high"] + Decimal("1")
    elif fault == "weekend_date" and row:
        saturday = date.fromisoformat(day)
        while saturday.weekday() != 5:
            saturday += timedelta(days=1)
        row["date"] = saturday.isoformat()
    elif fault == "identical_duplicate" and row:
        work.append(copy.deepcopy(row))
    elif fault == "conflicting_duplicate" and row:
        twin = copy.deepcopy(row)
        twin["close"] += Decimal("0.5")
        twin["high"] += Decimal("1")
        work.append(twin)
    elif fault == "price_jump" and row:
        row["close"] = row["close"] * Decimal("1.6")
        row["high"] = row["close"]
    elif fault == "zero_volume" and row:
        row["volume"] = Decimal("0")
    elif fault == "missing_session":
        work.pop(AT[fault])
    return day


@pytest.mark.parametrize("fault", sorted(EXPECTED))
def test_each_fault_is_caught_by_its_own_rule(
    corpus: dict[str, Records], gated: Any, run_gate: Any, fault: str
) -> None:
    baseline = {b.session_date: b.content_hash for b in gated[SYMBOL].clean}
    work = copy.deepcopy(corpus[SYMBOL])
    session = date.fromisoformat(apply_fault(work, fault, corpus[SYMBOL]))
    result = run_gate(work)
    kind, rule, loses_bar = EXPECTED[fault]

    rejected = {r.session_date: set(r.rules) for r in result.rejected}
    flagged = {b.session_date: set(b.flags) for b in result.clean if b.flags}
    if kind == "rejected":
        # a Saturday date is rejected under the Saturday, not the session it replaced
        saturdays = [d for d in rejected if d and d.weekday() == 5]
        key = saturdays[0] if "weekend" in fault else session
        assert rule in rejected.get(key, set()), f"{fault}: not rejected as {rule}"
    elif kind == "flagged":
        assert rule in flagged.get(session, set()), f"{fault}: not flagged as {rule}"
        assert session not in rejected
    elif kind == "deduplicated":
        assert not rejected and result.report["duplicates_removed"] == 1
    else:
        assert not rejected
    assert (session in result.gaps) is loses_bar, f"{fault}: gap reporting is wrong"

    # Nothing else may change: every other published bar is exactly what it was
    clean = {b.session_date: b.content_hash for b in result.clean}
    expected_dates = set(baseline) - ({session} if loses_bar else set())
    assert set(clean) == expected_dates, f"{fault}: a different set of bars was published"
    touched = {session} if fault in {"price_jump", "zero_volume"} else set()
    changed = {d for d in clean if clean[d] != baseline[d]}
    assert changed <= touched, f"{fault}: untouched bars changed {sorted(changed - touched)}"
    accounted = len(result.clean) + len(result.rejected) + result.report["duplicates_removed"]
    assert accounted == result.report["received"], f"{fault}: the report does not add up"


def test_all_faults_at_once_are_each_still_caught(
    corpus: dict[str, Records], run_gate: Any
) -> None:
    original = corpus[SYMBOL]
    work = copy.deepcopy(original)
    for fault in AT:
        apply_fault(work, fault, original)
    result = run_gate(work)
    rules = {rule for rej in result.rejected for rule in rej.rules}
    flags = {flag for bar in result.clean for flag in bar.flags}
    assert {"non_positive_price", "ohlc_order", "non_trading_day", "duplicate_conflict"} <= rules
    assert {"outlier", "zero_volume"} <= flags
    assert result.report["duplicates_removed"] == 1
    assert len(result.gaps) >= 4  # three lost sessions, the weekend one and the removed one
    accounted = len(result.clean) + len(result.rejected) + result.report["duplicates_removed"]
    assert accounted == result.report["received"]
