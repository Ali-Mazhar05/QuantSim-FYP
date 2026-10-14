"""Watch the cleaning gate and the returns calculation work on real data.

    uv run python scripts/gate_demo.py          # recorded AAPL bars plus planted faults
    uv run python scripts/gate_demo.py --live   # today's AAPL bars from Tiingo

``--live`` needs the API key in the QS_TIINGO_API_KEY environment variable; the key is
sent in a header and never printed. Nothing is written anywhere: this runs the same
pure functions the ingestion worker will call, and prints what they decided.
"""

import argparse
import json
import os
import sys
import urllib.request
from datetime import UTC, date, datetime, timedelta
from typing import Any

from qs_market.cleaning import run_gate
from qs_market.returns import PricePoint, compute

# Tiingo field names -> the cleaning gate's field names
TIINGO_FIELDS = {
    "date": "date",
    "open": "open",
    "high": "high",
    "low": "low",
    "close": "close",
    "volume": "volume",
    "adj_open": "adjOpen",
    "adj_high": "adjHigh",
    "adj_low": "adjLow",
    "adj_close": "adjClose",
    "adj_volume": "adjVolume",
    "dividend": "divCash",
    "split_factor": "splitFactor",
}

# Real Tiingo response for AAPL, 2025-10-27 .. 2025-10-31 (recorded 2026-10-11)
RECORDED = [
    ("2025-10-27", 264.88, 269.12, 264.6501, 268.81, 44888152, 267.8149818741),
    ("2025-10-28", 268.985, 269.89, 268.15, 269.0, 41534759, 268.0042785764),
    ("2025-10-29", 269.275, 271.41, 267.11, 269.7, 51086742, 268.7016874798),
    ("2025-10-30", 271.99, 274.14, 268.48, 271.4, 69886534, 270.3953948165),
    ("2025-10-31", 276.99, 277.32, 269.16, 270.37, 86167123, 269.3692074302),
]


def tiingo_record(
    day: str, o: float, h: float, lo: float, c: float, v: int, adj: float, **overrides: Any
) -> dict[str, Any]:
    ratio = adj / c
    record = {
        "date": f"{day}T00:00:00.000Z",
        "open": o,
        "high": h,
        "low": lo,
        "close": c,
        "volume": v,
        "adjOpen": o * ratio,
        "adjHigh": h * ratio,
        "adjLow": lo * ratio,
        "adjClose": adj,
        "adjVolume": v,
        "divCash": 0.0,
        "splitFactor": 1.0,
    }
    record.update(overrides)
    return record


def recorded_with_planted_faults() -> tuple[list[dict[str, Any]], dict[int, str]]:
    """The five real bars, plus records that each break one rule on purpose."""
    real = [tiingo_record(*row) for row in RECORDED]
    planted = [
        (tiingo_record(*RECORDED[1]), "identical copy of 10-28"),
        (tiingo_record(*RECORDED[2], close=999.0, high=999.0), "conflicting copy of 10-29"),
        (tiingo_record("2025-11-01", 270, 271, 269, 270.5, 1000, 270.5), "a Saturday"),
        (tiingo_record("2025-11-03", 270, 271, 272, 270.5, 1000, 270.5), "low above high"),
        (tiingo_record("2025-11-04", -1, 271, 269, 270.5, 1000, 270.5), "negative open"),
        (tiingo_record("2025-11-05", 270, 271, 269, 270.5, 0, 270.5), "zero volume"),
        (tiingo_record("2025-11-06", 440, 445, 438, 444.0, 1000, 444.0), "a 50% jump"),
        ({"date": "2025-11-07T00:00:00.000Z", "open": 270}, "fields missing"),
        (tiingo_record("2025-10-24", 260, 262, 259, 261, 1000, 261), "outside the window"),
    ]
    notes = {len(real) + i: note for i, (_, note) in enumerate(planted)}
    return real + [r for r, _ in planted], notes


def fetch_live(start: date, end: date) -> list[dict[str, Any]]:
    key = os.environ.get("QS_TIINGO_API_KEY")
    if not key:
        sys.exit("set QS_TIINGO_API_KEY to use --live")
    url = (
        f"https://api.tiingo.com/tiingo/daily/aapl/prices"
        f"?startDate={start.isoformat()}&endDate={end.isoformat()}"
    )
    request = urllib.request.Request(
        url, headers={"Authorization": f"Token {key}", "Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
        body: list[dict[str, Any]] = json.load(response)
    return body


def normalise(record: dict[str, Any]) -> dict[str, Any]:
    return {ours: record.get(theirs) for ours, theirs in TIINGO_FIELDS.items()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--live", action="store_true", help="fetch AAPL from Tiingo")
    args = parser.parse_args()

    if args.live:
        end = datetime.now(UTC).date()
        start = end - timedelta(days=14)
        raw = fetch_live(start, end)
        notes: dict[int, str] = {}
        as_of = datetime.now(UTC)
    else:
        start, end = date(2025, 10, 27), date(2025, 11, 10)
        raw, notes = recorded_with_planted_faults()
        as_of = datetime(2025, 11, 12, tzinfo=UTC)

    records = [normalise(r) for r in raw]
    result = run_gate(
        records,
        calendar="XNYS",
        window_start=start,
        window_end=end,
        as_of=as_of,
        previous_close=None,
        outlier_log_return=0.405,
    )

    print(f"\nWindow {start} .. {end}   ruleset {result.report['ruleset_version']}\n")
    print("Every record the vendor sent, and what the gate decided:")
    rejected_by_id = {id(r.payload): r.rules for r in result.rejected}
    published = {b.session_date: b for b in result.clean}
    shown: set[date] = set()
    for index, record in enumerate(records):
        day = str(record.get("date"))[:10]
        note = f"   <- planted: {notes[index]}" if index in notes else ""
        if id(record) in rejected_by_id:
            verdict = "REJECTED " + ", ".join(rejected_by_id[id(record)])
        else:
            try:
                bar = published.get(date.fromisoformat(day))
            except ValueError:
                bar = None
            flags = f" flags={list(bar.flags)}" if bar and bar.flags else ""
            if bar and bar.session_date not in shown:
                shown.add(bar.session_date)
                verdict = "published" + flags
            else:
                verdict = "duplicate removed (identical copy kept once)"
        print(f"  {day}  close={record.get('close')!s:<10} {verdict}{note}")

    print("\nPublished bars (prices rounded to 8 decimal places, close time in UTC):")
    for bar in result.clean:
        print(
            f"  {bar.session_date}  {bar.ts:%Y-%m-%d %H:%M} UTC  O {bar.open}  H {bar.high}"
            f"  L {bar.low}  C {bar.close}  adjC {bar.adj_close}  V {bar.volume:f}"
        )

    print(
        "\nData gaps (expected sessions with no clean bar):",
        [g.isoformat() for g in result.gaps] or "none",
    )

    report = result.report
    print("\nReconciliation report:")
    print(json.dumps({k: v for k, v in report.items() if k != "gaps"}, indent=2))
    total = (
        report["passed_untouched"]
        + report["corrected"]
        + report["duplicates_removed"]
        + report["rejected"]
    )
    print(
        f"\nCheck: received {report['received']} = passed {report['passed_untouched']}"
        f" + corrected {report['corrected']} + duplicates removed"
        f" {report['duplicates_removed']} + rejected {report['rejected']} = {total}"
    )

    returns = compute([PricePoint(b.session_date, b.close, b.adj_close) for b in result.clean])
    print("\nReturns from the published bars:")
    for point in returns:
        raw_r = "-" if point.log_return is None else f"{point.log_return:+.6f}"
        adj_r = "-" if point.adj_log_return is None else f"{point.adj_log_return:+.6f}"
        print(f"  {point.session_date}  log return {raw_r}   adjusted {adj_r}")
    print("  (20- and 60-session volatility appear once 20 and 60 returns exist)\n")


if __name__ == "__main__":
    main()
