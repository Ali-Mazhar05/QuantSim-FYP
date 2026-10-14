"""The cleaning gate (FR-MKT-011).

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
PRICE_STEP = Decimal("0.000001")
VOLUME_STEP = Decimal("0.00000001")
# A vendor needs a while after the close to publish the day's bar
PUBLICATION_GRACE = timedelta(hours=1)

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
    adj_close: Decimal | None
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
            "adj_close": None if self.adj_close is None else str(self.adj_close),
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
    adj_close: Decimal | None
    split_factor: Decimal
    dividend: Decimal

    @property
    def values(self) -> tuple[Decimal | None, ...]:
        return (
            self.open,
            self.high,
            self.low,
            self.close,
            self.volume,
            self.adj_close,
            self.split_factor,
            self.dividend,
        )


def _decimal(value: Any, step: Decimal) -> Decimal:
    if value is None or isinstance(value, bool):
        raise ValueError("missing")
    number = Decimal(str(value))
    if not number.is_finite():
        raise ValueError("not finite")
    return number.quantize(step, rounding=ROUND_HALF_EVEN)


def _parse(record: dict[str, Any]) -> _Parsed:
    for key in REQUIRED:
        if record.get(key) is None:
            raise ValueError(f"missing {key}")
    raw_date = record["date"]
    session_date = (
        raw_date if isinstance(raw_date, date) else date.fromisoformat(str(raw_date)[:10])
    )
    adj = record.get("adj_close")
    split = record.get("split_factor")
    dividend = record.get("dividend")
    try:
        return _Parsed(
            record=record,
            session_date=session_date,
            open=_decimal(record["open"], PRICE_STEP),
            high=_decimal(record["high"], PRICE_STEP),
            low=_decimal(record["low"], PRICE_STEP),
            close=_decimal(record["close"], PRICE_STEP),
            volume=_decimal(record["volume"], VOLUME_STEP),
            adj_close=None if adj is None else _decimal(adj, PRICE_STEP),
            split_factor=Decimal("1") if split is None else _decimal(split, Decimal("1e-10")),
            dividend=Decimal("0") if dividend is None else _decimal(dividend, PRICE_STEP),
        )
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(str(exc)) from exc


def content_hash(parsed: _Parsed) -> str:
    """Fingerprint of a bar's vendor content; identical data gives an identical hash."""
    canonical = "|".join(
        [parsed.session_date.isoformat(), *("" if v is None else str(v) for v in parsed.values)]
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _hard_failures(parsed: _Parsed, calendar: str, start: date, end: date) -> list[str]:
    rules = []
    if not start <= parsed.session_date <= end:
        rules.append("outside_window")
    if not calendars.is_session(calendar, parsed.session_date):
        rules.append("non_trading_day")
    prices = (parsed.open, parsed.high, parsed.low, parsed.close)
    if any(p <= 0 for p in prices):
        rules.append("non_positive_price")
    elif parsed.low > parsed.high or not (
        parsed.low <= parsed.open <= parsed.high and parsed.low <= parsed.close <= parsed.high
    ):
        rules.append("ohlc_order")
    if parsed.volume < 0:
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
                adj_close=parsed.adj_close,
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
