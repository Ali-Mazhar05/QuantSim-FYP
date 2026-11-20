"""The A-NFR-01 benchmark environment: 40 instruments over 252 daily sessions.

A-NFR-01 asks for a run over 40 instruments and 252 sessions to finish in under 60 s on
DEV. This module writes that environment as a fixture in the format of
:mod:`qs_trading.adapters.file_environment`, so the DEV worker serves it from the bundled
demo environments under :data:`ENV_ID`.

The prices are a seeded random walk computed in whole ten-thousandths with integer
arithmetic only (``random.Random.randrange`` on a fixed seed), so the file is the same
byte for byte on every machine and Python version. Each instrument has its own drift, so
momentum has something to rank. Regenerate it with::

    uv run python -m qs_trading.demo.benchmark            # rewrites the bundled file
    uv run python -m qs_trading.demo.benchmark --check    # exits 1 if it differs

The file has one tick per line and no indentation, and the ticks leave out the
market.tick.v1 fields the adapter ignores and the ``environment`` object already gives
(``env_id``, ``env_type``, ``source_fingerprint``, ``path_index``, ``scenario``), to keep
it under 3 MB.
"""

import argparse
import json
import random
import sys
from datetime import date, timedelta
from pathlib import Path

__all__ = [
    "ENV_ID",
    "INSTRUMENTS",
    "PATH",
    "SESSIONS",
    "build",
]

ENV_ID = "5d0c6c1e-7a14-4a14-8a14-000000000040"
INSTRUMENTS = 40
SESSIONS = 252
SEED = 40252
FIRST_DAY = date(2025, 1, 2)
PATH = Path(__file__).resolve().parent / "environments" / f"{ENV_ID}.json"

_UNIT = 10_000  # prices are whole ten-thousandths
_BPS = 10_000


def _price(units: int) -> str:
    """``units`` ten-thousandths as a decimal string with 2 to 4 decimals."""
    whole, fraction = divmod(units, _UNIT)
    digits = f"{fraction:04d}"
    while len(digits) > 2 and digits.endswith("0"):
        digits = digits[:-1]
    return f"{whole}.{digits}"


def _sessions() -> list[date]:
    """``SESSIONS`` weekdays from ``FIRST_DAY`` (no holiday calendar)."""
    days: list[date] = []
    day = FIRST_DAY
    while len(days) < SESSIONS:
        if day.weekday() < 5:
            days.append(day)
        day += timedelta(days=1)
    return days


def _dumps(value: object) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def build() -> bytes:
    """The fixture's bytes; the same on every call."""
    rng = random.Random(SEED)  # noqa: S311 - reproducible test data, not secrets
    symbols = [f"N{number:02d}" for number in range(1, INSTRUMENTS + 1)]
    instrument_ids = [
        f"00000000-0000-4000-8040-{number:012d}" for number in range(1, INSTRUMENTS + 1)
    ]
    closes = [rng.randrange(20 * _UNIT, 300 * _UNIT) for _ in symbols]
    drifts = [rng.randrange(-8, 9) for _ in symbols]  # bps per session
    days = _sessions()

    environment = {
        "id": ENV_ID,
        "name": "A-NFR-01 40x252 benchmark",
        "type": "historical_replay",
        "frequency": "daily",
        "start_date": days[0].isoformat(),
        "end_date": days[-1].isoformat(),
        "instruments": [
            {"id": instrument_id, "symbol": symbol}
            for instrument_id, symbol in zip(instrument_ids, symbols, strict=True)
        ],
        "tick_count": INSTRUMENTS * SESSIONS,
    }
    meta = {
        "contract": "market.tick.v1",
        "made_by": "qs_trading.demo.benchmark",
        "note": (
            "A-NFR-01 performance benchmark: 40 instruments x 252 daily sessions, a seeded"
            " random walk. Generated; do not edit by hand."
        ),
    }
    lines = ["{", f'"meta":{_dumps(meta)},', f'"environment":{_dumps(environment)},', '"items":[']
    seq = 0
    for session, day in enumerate(days):
        stamp = f"{day.isoformat()}T21:00:00Z"
        for index, symbol in enumerate(symbols):
            previous = closes[index]
            if session == 0:
                open_ = previous
            else:
                open_ = previous * (_BPS + rng.randrange(-50, 51)) // _BPS
            close = open_ * (_BPS + drifts[index] + rng.randrange(-200, 201)) // _BPS
            high = max(open_, close) * (_BPS + rng.randrange(0, 101)) // _BPS
            low = min(open_, close) * (_BPS - rng.randrange(0, 101)) // _BPS
            volume = rng.randrange(200_000, 5_000_001)
            closes[index] = close
            seq += 1
            tick = {
                "seq": seq,
                "session": session,
                "session_date": day.isoformat(),
                "ts": stamp,
                "instrument_id": instrument_ids[index],
                "symbol": symbol,
                "open": _price(open_),
                "high": _price(high),
                "low": _price(low),
                "close": _price(close),
                "volume": str(volume),
            }
            last = seq == INSTRUMENTS * SESSIONS
            lines.append(_dumps(tick) + ("" if last else ","))
    lines.extend(["]", "}", ""])
    return "\n".join(lines).encode()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="compare, do not write")
    parser.add_argument("--out", type=Path, default=PATH, help="where to write the fixture")
    args = parser.parse_args(argv)
    content = build()
    if args.check:
        current = args.out.read_bytes().replace(b"\r\n", b"\n") if args.out.exists() else b""
        if current != content:
            print(f"{args.out} is not what the generator writes", file=sys.stderr)
            return 1
        print(f"{args.out} is up to date")
        return 0
    args.out.write_bytes(content)
    print(f"wrote {args.out} ({len(content)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
