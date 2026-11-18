"""Replay ticks from stored bars (ADR 01, ADR 08): pure functions, no database.

One function turns the adjusted bars of an environment into the ticks of the contract
``market.tick.v1``. The recorded fixtures and the feed endpoint both use it, so they cannot
disagree. Decimals are written at the scale of the column they come from, so a value reads the same
whether it came from the database or from a recorded file.
"""

import uuid
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import xxhash

PRICE_SCALE = Decimal("1E-10")  # adjusted prices are NUMERIC(23, 10)
VOLUME_SCALE = Decimal("1E-8")  # adjusted volume is NUMERIC(28, 8)
FINGERPRINT_PREFIX = "xxh3:"


class MissingAdjustedPrices(Exception):
    """A bar in the window has no adjusted value; raw prices are never substituted (ADR 08)."""

    def __init__(self, missing: dict[str, int]) -> None:
        self.missing = missing
        listed = ", ".join(f"{symbol} ({count})" for symbol, count in sorted(missing.items()))
        super().__init__(f"bars without adjusted prices: {listed}")


@dataclass(frozen=True)
class BarRow:
    """What the feed reads of a stored bar."""

    instrument_id: uuid.UUID
    symbol: str
    session_date: date
    ts: datetime  # the session close
    revision: int
    adj_open: Decimal | None
    adj_high: Decimal | None
    adj_low: Decimal | None
    adj_close: Decimal | None
    adj_volume: Decimal | None


def _price(value: Decimal) -> str:
    return format(value.quantize(PRICE_SCALE), "f")


def _volume(value: Decimal) -> str:
    return format(value.quantize(VOLUME_SCALE), "f")


def utc_text(value: datetime) -> str:
    """A timestamp as the contract writes it: ISO 8601 in UTC with a Z."""
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def ordered(rows: Sequence[BarRow]) -> list[BarRow]:
    """The feed order: by session, then symbol (the instrument id breaks a tie, so it is total)."""
    return sorted(rows, key=lambda r: (r.session_date, r.symbol, str(r.instrument_id)))


def missing_adjusted(rows: Sequence[BarRow]) -> dict[str, int]:
    """Bars with any adjusted value missing, counted per symbol."""
    counts: dict[str, int] = {}
    for r in rows:
        values = (r.adj_open, r.adj_high, r.adj_low, r.adj_close, r.adj_volume)
        if any(v is None for v in values):
            counts[r.symbol] = counts.get(r.symbol, 0) + 1
    return counts


def _require_adjusted(rows: Sequence[BarRow]) -> None:
    missing = missing_adjusted(rows)
    if missing:
        raise MissingAdjustedPrices(missing)


def canonical_line(r: BarRow) -> str:
    """One bar as the fingerprint reads it: instrument, session, revision and the five adjusted
    values at their column scale. For stored values PostgreSQL writes exactly this text (the replay
    service asks it to, so a large window is not pulled into Python); a test holds the two equal."""
    assert r.adj_open is not None and r.adj_high is not None  # callers check for gaps first
    assert r.adj_low is not None and r.adj_close is not None and r.adj_volume is not None
    return "|".join(
        (
            str(r.instrument_id),
            r.session_date.isoformat(),
            str(r.revision),
            _price(r.adj_open),
            _price(r.adj_high),
            _price(r.adj_low),
            _price(r.adj_close),
            _volume(r.adj_volume),
        )
    )


def fingerprint_of_lines(lines: Iterable[str]) -> str:
    """xxh3 over canonical lines already in feed order."""
    digest = xxhash.xxh3_128()
    for line in lines:
        digest.update(f"{line}\n".encode())
    return FINGERPRINT_PREFIX + digest.hexdigest()


def fingerprint(rows: Sequence[BarRow]) -> str:
    """Identifies the exact data served: xxh3 over the ordered served values and revisions.

    It changes when a revision lands or when the vendor restates an adjusted price inside the
    window; it does not depend on the order the rows were read in (ADR 08).
    """
    _require_adjusted(rows)
    return fingerprint_of_lines(canonical_line(r) for r in ordered(rows))


def missing_session_count(rows: Sequence[BarRow], instrument_count: int) -> int:
    """Sessions on which some instrument of the environment has no bar (ADR 08)."""
    per_session = Counter(r.session_date for r in rows)
    return sum(1 for count in per_session.values() if count < instrument_count)


def tick(
    r: BarRow, seq: int, session: int, env_id: uuid.UUID, source_fingerprint: str
) -> dict[str, Any]:
    assert r.adj_open is not None and r.adj_high is not None  # checked by the callers
    assert r.adj_low is not None and r.adj_close is not None and r.adj_volume is not None
    return {
        "env_id": str(env_id),
        "env_type": "replay",
        "source_fingerprint": source_fingerprint,
        "seq": seq,
        "session": session,
        "session_date": r.session_date.isoformat(),
        "ts": utc_text(r.ts),
        "instrument_id": str(r.instrument_id),
        "symbol": r.symbol,
        "open": _price(r.adj_open),
        "high": _price(r.adj_high),
        "low": _price(r.adj_low),
        "close": _price(r.adj_close),
        "volume": _volume(r.adj_volume),
        "path_index": None,
        "scenario": None,
    }


def _sessions(feed: Sequence[BarRow]) -> dict[date, int]:
    return {day: i for i, day in enumerate(sorted({r.session_date for r in feed}))}


def build_ticks(
    rows: Sequence[BarRow], *, env_id: uuid.UUID, source_fingerprint: str
) -> list[dict[str, Any]]:
    """The ticks of a replay environment, ordered by (session, symbol) with seq 1, 2, 3 and no gap.

    ``session`` is the zero-based index of the session among the sessions present. A symbol with no
    bar on a session simply has no tick on it; seq stays gap-free over the ticks emitted.
    """
    _require_adjusted(rows)
    feed = ordered(rows)
    sessions = _sessions(feed)
    return [
        tick(r, seq, sessions[r.session_date], env_id, source_fingerprint)
        for seq, r in enumerate(feed, start=1)
    ]


def build_page(
    rows: Sequence[BarRow],
    *,
    env_id: uuid.UUID,
    source_fingerprint: str,
    after_seq: int,
    limit: int,
) -> tuple[list[dict[str, Any]], int | None]:
    """One page of the feed and the cursor for the next, built without making every tick.

    The same ticks as ``build_ticks(...)[after_seq : after_seq + limit]``; the cursor is the ``seq``
    of the last tick when more follow, and None on the last page.
    """
    _require_adjusted(rows)
    feed = ordered(rows)
    sessions = _sessions(feed)
    items = [
        tick(r, after_seq + offset, sessions[r.session_date], env_id, source_fingerprint)
        for offset, r in enumerate(feed[after_seq : after_seq + limit], start=1)
    ]
    more = after_seq + limit < len(feed)
    return items, (int(items[-1]["seq"]) if items and more else None)


def page(
    ticks: Sequence[dict[str, Any]], after_seq: int, limit: int
) -> tuple[list[dict[str, Any]], int | None]:
    """One page after ``after_seq`` and the cursor for the next, or None on the last page.

    seq is the position (starting at 1) in the full feed, so the page is a slice.
    """
    items = list(ticks[after_seq : after_seq + limit])
    more = after_seq + limit < len(ticks)
    return items, (int(items[-1]["seq"]) if items and more else None)
