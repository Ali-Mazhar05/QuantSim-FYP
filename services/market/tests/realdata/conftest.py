"""Real vendor data for the real-data tests.

The corpus is recorded by ``scripts/fetch_realdata.py`` (never committed). Without it
every test in this folder is skipped, so CI and fresh clones stay green; with it, the
same checks that the unit tests make on constructed bars run on years of real ones.
"""

import json
import os
from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from qs_market import cleaning, returns

SYMBOLS = ("AAPL", "MSFT", "NVDA", "TSLA", "KO", "SPY")
CORPUS_DIR = Path(os.environ.get("QS_REALDATA_DIR", Path(__file__).parent / "corpus"))
CALENDAR = "XNYS"
NUMERIC = (
    "open",
    "high",
    "low",
    "close",
    "volume",
    "adj_open",
    "adj_high",
    "adj_low",
    "adj_close",
    "adj_volume",
    "split_factor",
    "dividend",
)

Records = list[dict[str, Any]]


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    missing = [s for s in SYMBOLS if not (CORPUS_DIR / f"{s}.json").exists()]
    if not missing:
        return
    skip = pytest.mark.skip(
        reason=f"no recorded corpus in {CORPUS_DIR} (run scripts/fetch_realdata.py); "
        f"missing {', '.join(missing)}"
    )
    for item in items:
        if "realdata" in item.keywords:
            item.add_marker(skip)


def _load(symbol: str) -> Records:
    document = json.loads((CORPUS_DIR / f"{symbol}.json").read_text(encoding="utf-8"))
    records: Records = document["records"]
    for record in records:
        for key in NUMERIC:
            if record.get(key) is not None:
                record[key] = Decimal(str(record[key]))
    return records


@pytest.fixture(scope="session")
def corpus() -> dict[str, Records]:
    return {symbol: _load(symbol) for symbol in SYMBOLS}


@pytest.fixture(scope="session")
def window(corpus: dict[str, Records]) -> tuple[date, date]:
    dates = [date.fromisoformat(r["date"]) for rows in corpus.values() for r in rows]
    return min(dates), max(dates)


@pytest.fixture(scope="session")
def run_gate(window: tuple[date, date]) -> Any:
    """The gate configured the way an ingestion run configures it for XNYS."""

    def _run(records: Records, **overrides: Any) -> cleaning.GateResult:
        options: dict[str, Any] = {
            "calendar": CALENDAR,
            "window_start": window[0],
            "window_end": window[1],
            "as_of": datetime.now(UTC),
            "previous_close": None,
            "outlier_log_return": 0.405,
        }
        options.update(overrides)
        return cleaning.run_gate(records, **options)

    return _run


@pytest.fixture(scope="session")
def gated(corpus: dict[str, Records], run_gate: Any) -> dict[str, cleaning.GateResult]:
    """Every symbol through the gate once; the tests below share the results."""
    return {symbol: run_gate(records) for symbol, records in corpus.items()}


@pytest.fixture(scope="session")
def series(gated: dict[str, cleaning.GateResult]) -> dict[str, list[returns.ReturnPoint]]:
    """Returns and volatility for every symbol, computed once (it is the slow part)."""
    return {
        name: returns.compute(
            [returns.PricePoint(b.session_date, b.close, b.adj_close) for b in result.clean]
        )
        for name, result in gated.items()
    }


@pytest.fixture(params=SYMBOLS)
def symbol(request: pytest.FixtureRequest) -> Iterator[str]:
    yield request.param
