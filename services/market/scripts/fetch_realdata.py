"""Record a corpus of real end-of-day bars for the real-data tests.

    TIINGO_API_KEY=... uv run python scripts/fetch_realdata.py
    TIINGO_API_KEY=... uv run python scripts/fetch_realdata.py --symbols AAPL KO --start 2020-01-02

It goes through the same adapter the ingestion service uses, so the recorded rows are in
the cleaning gate's shape. One request per symbol (the free tier allows 50 an hour). The
corpus is written to ``tests/realdata/corpus`` (override with ``--out`` or
``QS_REALDATA_DIR``), which git ignores: the free tier is for personal use, so the data
is fetched on demand and never committed.

The key is read from the environment and is never printed or written.
"""

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from pydantic import SecretStr

from qs_market.vendor.tiingo import TiingoSource

# Chosen for their differences: large caps, four real splits, steady dividends, an ETF
DEFAULT_SYMBOLS = ["AAPL", "MSFT", "NVDA", "TSLA", "KO", "SPY"]
DEFAULT_OUT = Path(__file__).resolve().parents[1] / "tests" / "realdata" / "corpus"


def _plain(value: object) -> object:
    return str(value) if isinstance(value, Decimal) else value


async def record(symbols: list[str], start: date, end: date, out: Path) -> int:
    key = os.environ.get("TIINGO_API_KEY", "")
    if not key:
        print("TIINGO_API_KEY is not set", file=sys.stderr)
        return 2
    source = TiingoSource(SecretStr(key))
    failures = 0
    try:
        for symbol in symbols:
            started = time.perf_counter()
            try:
                rows = await source.fetch_daily(symbol, start, end)
            except Exception as exc:  # report and carry on with the next symbol
                failures += 1
                print(f"{symbol:6} FAILED  {type(exc).__name__}")
                continue
            document = {
                "symbol": symbol,
                "vendor": "tiingo",
                "start": start.isoformat(),
                "end": end.isoformat(),
                "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "records": [{k: _plain(v) for k, v in row.items()} for row in rows],
            }
            await asyncio.to_thread(
                (out / f"{symbol}.json").write_text,
                json.dumps(document, indent=1),
                encoding="utf-8",
            )
            print(
                f"{symbol:6} {len(rows):5} rows  {time.perf_counter() - started:5.1f}s  "
                f"{rows[0]['date'] if rows else '-'} .. {rows[-1]['date'] if rows else '-'}"
            )
            await asyncio.sleep(1)
    finally:
        await source.aclose()
    print(f"written to {out}")
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--symbols", nargs="+", default=DEFAULT_SYMBOLS)
    parser.add_argument("--start", type=date.fromisoformat, default=date(2015, 1, 2))
    parser.add_argument("--end", type=date.fromisoformat, default=None)
    parser.add_argument(
        "--out", type=Path, default=Path(os.environ.get("QS_REALDATA_DIR", DEFAULT_OUT))
    )
    args = parser.parse_args()
    end = args.end or datetime.now(UTC).date()
    args.out.mkdir(parents=True, exist_ok=True)
    return asyncio.run(record(args.symbols, args.start, end, args.out))


if __name__ == "__main__":
    raise SystemExit(main())
