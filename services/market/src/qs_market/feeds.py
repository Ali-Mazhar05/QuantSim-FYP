"""Replay ticks from stored bars (ADR 01, ADR 08): pure functions, no database.

One function turns the adjusted bars of an environment into the ticks of the contract
``market.tick.v1``. The recorded fixtures and the feed endpoint both use it, so they cannot
disagree. Decimals are written at the scale of the column they come from, so a value reads the same
whether it came from the database or from a recorded file.
"""

import uuid
from collections.abc import Sequence
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
    """The feed order: by session, then by symbol."""
    return sorted(rows, key=lambda r: (r.session_date, r.symbol))


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


def fingerprint(rows: Sequence[BarRow]) -> str:
    """Identifies the exact data served: xxh3 over the ordered served values and revisions.

    It changes when a revision lands or when the vendor restates an adjusted price inside the
    window; it does not depend on the order the rows were read in (ADR 08).
    """
    _require_adjusted(rows)
    digest = xxhash.xxh3_128()
    for r in ordered(rows):
        assert r.adj_open is not None and r.adj_high is not None  # checked above
        assert r.adj_low is not None and r.adj_close is not None and r.adj_volume is not None
        line = "|".join(
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
        digest.update(f"{line}\n".encode())
    return FINGERPRINT_PREFIX + digest.hexdigest()


def build_ticks(
    rows: Sequence[BarRow], *, env_id: uuid.UUID, source_fingerprint: str
) -> list[dict[str, Any]]:
    """The ticks of a replay environment, ordered by (session, symbol) with seq 1, 2, 3 and no gap.

    ``session`` is the zero-based index of the session among the sessions present. A symbol with no
    bar on a session simply has no tick on it; seq stays gap-free over the ticks emitted.
    """
    _require_adjusted(rows)
    feed = ordered(rows)
    sessions = {day: i for i, day in enumerate(sorted({r.session_date for r in feed}))}
    ticks: list[dict[str, Any]] = []
    for seq, r in enumerate(feed, start=1):
        assert r.adj_open is not None and r.adj_high is not None  # checked above
        assert r.adj_low is not None and r.adj_close is not None and r.adj_volume is not None
        ticks.append(
            {
                "env_id": str(env_id),
                "env_type": "replay",
                "source_fingerprint": source_fingerprint,
                "seq": seq,
                "session": sessions[r.session_date],
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
        )
    return ticks


def page(
    ticks: Sequence[dict[str, Any]], after_seq: int, limit: int
) -> tuple[list[dict[str, Any]], int | None]:
    """One page after ``after_seq`` and the cursor for the next, or None on the last page.

    seq is the position (starting at 1) in the full feed, so the page is a slice.
    """
    items = list(ticks[after_seq : after_seq + limit])
    more = after_seq + limit < len(ticks)
    return items, (int(items[-1]["seq"]) if items and more else None)
