"""The cleaning gate (FR-MKT-011, PRD FR-25 and FR-26).

Nothing reaches the published ``bar`` table, or the ``bar.ingested`` event, without
passing here. Each vendor record is checked against these rules:

| Rule                 | Severity | Outcome                                               |
|----------------------|----------|-------------------------------------------------------|
| malformed            | reject   | missing or unparsable fields                          |
| outside_window       | reject   | a date the run did not ask for                        |
| non_trading_day      | reject   | weekend or exchange holiday                           |
| non_positive_price   | reject   | any of open, high, low, close <= 0                    |
| ohlc_order           | reject   | low > high, or open/close outside [low, high]         |
| negative_volume      | reject   | volume < 0                                            |
| duplicate_conflict   | reject   | the same session twice with different values          |
| duplicate_removed    | correct  | the same session twice with identical values: keep one|
| zero_volume          | flag     | published with the flag                               |
| outlier              | flag     | absolute log return above the threshold (or reject,  |
|                      |          | by policy); skipped on split days                     |
| missing_session      | record   | an expected session with no clean bar: a data gap     |

Every bar is timestamped with its session's close in UTC. The report states what was
passed untouched, corrected, removed and rejected, and why; the counts always add up to
the number of records received.
"""

import hashlib
import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation
from typing import Any, Literal

from qs_market import calendars

RULESET_VERSION = "2026.10.1"
PRICE_STEP = Decimal("0.00000001")  # 8 decimal places, as stored
# The vendor restates adjusted prices with ten decimals, and the column keeps them
ADJUSTED_PRICE_STEP = Decimal("0.0000000001")
VOLUME_STEP = Decimal("0.00000001")
FACTOR_STEP = Decimal("0.0000000001")
# Largest magnitudes the database columns can hold (NUMERIC(23,8), (28,8) and (20,10)); a
# value at or above them would pass the gate and then fail at insert, so it is malformed
PRICE_LIMIT = Decimal(10) ** 15
VOLUME_LIMIT = Decimal(10) ** 20
FACTOR_LIMIT = Decimal(10) ** 10
# A session only counts as missing once its close plus this much has passed, so the 09:30
# UTC catch-up run is the first to judge it (vendors publish end-of-day data late). It
# must stay later than the latest close (21:00 UTC) plus this grace.
PUBLICATION_GRACE = timedelta(hours=12)
ADJUSTED = ("adj_open", "adj_high", "adj_low", "adj_close", "adj_volume")

REQUIRED = ("date", "open", "high", "low", "close", "volume")


@dataclass(frozen=True)
class CleanBar:
    session_date: date
    ts: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    adj_open: Decimal | None
    adj_high: Decimal | None
    adj_low: Decimal | None
    adj_close: Decimal | None
    adj_volume: Decimal | None
    split_factor: Decimal
    dividend: Decimal
    flags: tuple[str, ...]
    content_hash: str

    def as_json(self) -> dict[str, Any]:
        return {
            "session_date": self.session_date.isoformat(),
            "ts": self.ts.isoformat(),
            "open": str(self.open),
            "high": str(self.high),
            "low": str(self.low),
            "close": str(self.close),
            "volume": str(self.volume),
            **{name: _text(getattr(self, name)) for name in ADJUSTED},
            "split_factor": str(self.split_factor),
            "dividend": str(self.dividend),
            "flags": list(self.flags),
        }


@dataclass(frozen=True)
class Rejection:
    session_date: date | None
    rules: tuple[str, ...]
    payload: dict[str, Any]


@dataclass
class GateResult:
    clean: list[CleanBar]
    rejected: list[Rejection]
    gaps: list[date]
    report: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class _Parsed:
    record: dict[str, Any]
    session_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    adj_open: Decimal | None
    adj_high: Decimal | None
    adj_low: Decimal | None
    adj_close: Decimal | None
    adj_volume: Decimal | None
    split_factor: Decimal
    dividend: Decimal

    @property
    def values(self) -> tuple[Decimal | None, ...]:
        """Every value that is stored on the bar."""
        return (
            self.open,
            self.high,
            self.low,
            self.close,
            self.volume,
            self.adj_open,
            self.adj_high,
            self.adj_low,
            self.adj_close,
            self.adj_volume,
            self.split_factor,
            self.dividend,
        )

    @property
    def vendor_values(self) -> tuple[Decimal, ...]:
        """What the vendor said happened on this session. The adjusted columns are left
        out on purpose: the vendor restates them backwards at every dividend or split, so
        hashing them would make a restatement look like a correction of every old bar."""
        return (
            self.open,
            self.high,
            self.low,
            self.close,
            self.volume,
            self.split_factor,
            self.dividend,
        )


def _text(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _optional(value: Any, step: Decimal, limit: Decimal) -> Decimal | None:
    return None if value is None else _decimal(value, step, limit)


def _decimal(value: Any, step: Decimal, limit: Decimal) -> Decimal:
    if value is None or isinstance(value, bool):
        raise ValueError("missing")
    number = Decimal(str(value))
    if not number.is_finite():
        raise ValueError("not finite")
    if abs(number) >= limit:
        raise ValueError("out of range")
    return number.quantize(step, rounding=ROUND_HALF_EVEN)


def _parse(record: dict[str, Any]) -> _Parsed:
    for key in REQUIRED:
        if record.get(key) is None:
            raise ValueError(f"missing {key}")
    raw_date = record["date"]
    session_date = (
        raw_date if isinstance(raw_date, date) else date.fromisoformat(str(raw_date)[:10])
    )
    split = record.get("split_factor")
    dividend = record.get("dividend")
    try:
        parsed = _Parsed(
            record=record,
            session_date=session_date,
            open=_decimal(record["open"], PRICE_STEP, PRICE_LIMIT),
            high=_decimal(record["high"], PRICE_STEP, PRICE_LIMIT),
            low=_decimal(record["low"], PRICE_STEP, PRICE_LIMIT),
            close=_decimal(record["close"], PRICE_STEP, PRICE_LIMIT),
            volume=_decimal(record["volume"], VOLUME_STEP, VOLUME_LIMIT),
            adj_open=_optional(record.get("adj_open"), ADJUSTED_PRICE_STEP, PRICE_LIMIT),
            adj_high=_optional(record.get("adj_high"), ADJUSTED_PRICE_STEP, PRICE_LIMIT),
            adj_low=_optional(record.get("adj_low"), ADJUSTED_PRICE_STEP, PRICE_LIMIT),
            adj_close=_optional(record.get("adj_close"), ADJUSTED_PRICE_STEP, PRICE_LIMIT),
            adj_volume=_optional(record.get("adj_volume"), VOLUME_STEP, VOLUME_LIMIT),
            split_factor=Decimal("1")
            if split is None
            else _decimal(split, FACTOR_STEP, FACTOR_LIMIT),
            dividend=Decimal("0")
            if dividend is None
            else _decimal(dividend, PRICE_STEP, PRICE_LIMIT),
        )
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(str(exc)) from exc
    # The database refuses these, so they must not get past the gate
    if parsed.split_factor <= 0:
        raise ValueError("split factor must be positive")
    if parsed.dividend < 0:
        raise ValueError("dividend must not be negative")
    return parsed


def content_hash(parsed: _Parsed) -> str:
    """Fingerprint of what the vendor reported for the session; identical data gives an
    identical hash. Restated adjusted prices do not change it (see ``vendor_values``)."""
    canonical = "|".join([parsed.session_date.isoformat(), *(str(v) for v in parsed.vendor_values)])
    return hashlib.sha256(canonical.encode()).hexdigest()


def _hard_failures(parsed: _Parsed, calendar: str, start: date, end: date) -> list[str]:
    rules = []
    if not start <= parsed.session_date <= end:
        rules.append("outside_window")
    if not calendars.is_session(calendar, parsed.session_date):
        rules.append("non_trading_day")
    prices = (parsed.open, parsed.high, parsed.low, parsed.close)
    adjusted = (parsed.adj_open, parsed.adj_high, parsed.adj_low, parsed.adj_close)
    if any(p <= 0 for p in prices) or any(p is not None and p <= 0 for p in adjusted):
        rules.append("non_positive_price")
    elif parsed.low > parsed.high or not (
        parsed.low <= parsed.open <= parsed.high and parsed.low <= parsed.close <= parsed.high
    ):
        rules.append("ohlc_order")
    if parsed.volume < 0 or (parsed.adj_volume is not None and parsed.adj_volume < 0):
        rules.append("negative_volume")
    return rules


def run_gate(
    records: list[dict[str, Any]],
    *,
    calendar: str,
    window_start: date,
    window_end: date,
    as_of: datetime,
    previous_close: Decimal | None,
    outlier_log_return: float,
    outlier_policy: Literal["flag", "reject"] = "flag",
) -> GateResult:
    """Clean one instrument's records for one window. Pure: no I/O."""
    by_rule: Counter[str] = Counter()
    flagged: Counter[str] = Counter()
    rejected: list[Rejection] = []

    # 1. Parse and apply the per-record rules
    candidates: dict[date, list[_Parsed]] = defaultdict(list)
    for record in records:
        try:
            parsed = _parse(record)
        except (ValueError, TypeError):
            rejected.append(Rejection(None, ("malformed",), record))
            by_rule["malformed"] += 1
            continue
        failures = _hard_failures(parsed, calendar, window_start, window_end)
        if failures:
            rejected.append(Rejection(parsed.session_date, tuple(failures), record))
            by_rule.update(failures)
            continue
        candidates[parsed.session_date].append(parsed)

    # 2. Resolve duplicates
    corrected_dates: set[date] = set()
    duplicates_removed = 0
    survivors: list[_Parsed] = []
    for session_date in sorted(candidates):
        copies = candidates[session_date]
        if len(copies) == 1:
            survivors.append(copies[0])
        elif len({c.values for c in copies}) == 1:
            survivors.append(copies[0])
            corrected_dates.add(session_date)
            duplicates_removed += len(copies) - 1
            by_rule["duplicate_removed"] += len(copies) - 1
        else:
            for copy in copies:
                rejected.append(Rejection(session_date, ("duplicate_conflict",), copy.record))
            by_rule["duplicate_conflict"] += len(copies)

    # 3. Flags that need the previous close, in session order
    clean: list[CleanBar] = []
    prior = previous_close
    for parsed in survivors:
        flags = []
        if parsed.volume == 0:
            flags.append("zero_volume")
        if prior is not None and prior > 0 and parsed.split_factor == 1:
            move = abs(math.log(float(parsed.close) / float(prior)))
            if move > outlier_log_return:
                flags.append("outlier")
        if "outlier" in flags and outlier_policy == "reject":
            rejected.append(Rejection(parsed.session_date, ("outlier",), parsed.record))
            by_rule["outlier"] += 1
            corrected_dates.discard(parsed.session_date)
            continue
        flagged.update(flags)
        clean.append(
            CleanBar(
                session_date=parsed.session_date,
                ts=calendars.session_close(calendar, parsed.session_date),
                open=parsed.open,
                high=parsed.high,
                low=parsed.low,
                close=parsed.close,
                volume=parsed.volume,
                adj_open=parsed.adj_open,
                adj_high=parsed.adj_high,
                adj_low=parsed.adj_low,
                adj_close=parsed.adj_close,
                adj_volume=parsed.adj_volume,
                split_factor=parsed.split_factor,
                dividend=parsed.dividend,
                flags=tuple(flags),
                content_hash=content_hash(parsed),
            )
        )
        prior = parsed.close

    # 4. Gaps: sessions the vendor should have by now with no clean bar
    have = {b.session_date for b in clean}
    expected = calendars.closed_sessions(
        calendar, window_start, window_end, as_of=as_of, grace=PUBLICATION_GRACE
    )
    gaps = [s for s in expected if s not in have]

    corrected = sum(1 for b in clean if b.session_date in corrected_dates)
    report = {
        "ruleset_version": RULESET_VERSION,
        "received": len(records),
        "passed_untouched": len(clean) - corrected,
        "corrected": corrected,
        "duplicates_removed": duplicates_removed,
        "rejected": len(rejected),
        "by_rule": dict(sorted(by_rule.items())),
        "flagged": dict(sorted(flagged.items())),
        "gaps": [g.isoformat() for g in gaps],
    }
    return GateResult(clean=clean, rejected=rejected, gaps=gaps, report=report)
