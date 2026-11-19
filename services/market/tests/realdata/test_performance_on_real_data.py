"""Is it fast enough? Budgets for the planned workload, on real bars.

The plan is about 40 instruments and an 11 year first backfill (about 3,000 bars each),
then roughly 60 bars a day per instrument. The budgets below are deliberately loose, so a
slow CI machine does not fail them, but a change that makes the code ten times slower
does. Override with QS_REALDATA_GATE_SECONDS, QS_REALDATA_RETURNS_SECONDS and
QS_REALDATA_MEMORY_MB.
"""

import os
import time
import tracemalloc
from typing import Any

import pytest

from qs_market import cleaning, returns

from .conftest import Records

pytestmark = pytest.mark.realdata

GATE_SECONDS = float(os.environ.get("QS_REALDATA_GATE_SECONDS", "30"))
RETURNS_SECONDS = float(os.environ.get("QS_REALDATA_RETURNS_SECONDS", "30"))
MEMORY_MB = float(os.environ.get("QS_REALDATA_MEMORY_MB", "100"))


def test_gating_a_full_history_stays_within_budget(
    corpus: dict[str, Records], run_gate: Any, symbol: str
) -> None:
    started = time.perf_counter()
    result = run_gate(corpus[symbol])
    elapsed = time.perf_counter() - started
    bars = len(result.clean)
    assert elapsed < GATE_SECONDS, (
        f"{symbol}: {bars} bars took {elapsed:.1f}s ({bars / elapsed:.0f} bars/s), "
        f"budget {GATE_SECONDS:.0f}s"
    )


def test_computing_returns_for_a_full_history_stays_within_budget(
    gated: dict[str, cleaning.GateResult], symbol: str
) -> None:
    points = [returns.PricePoint(b.session_date, b.close, b.adj_close) for b in gated[symbol].clean]
    started = time.perf_counter()
    returns.compute(points)
    elapsed = time.perf_counter() - started
    assert elapsed < RETURNS_SECONDS, (
        f"{symbol}: {len(points)} points took {elapsed:.1f}s, budget {RETURNS_SECONDS:.0f}s"
    )


def test_one_symbol_needs_little_memory(corpus: dict[str, Records], run_gate: Any) -> None:
    tracemalloc.start()
    try:
        result = run_gate(corpus["AAPL"])
        returns.compute(
            [returns.PricePoint(b.session_date, b.close, b.adj_close) for b in result.clean]
        )
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak / 1024 / 1024 < MEMORY_MB, f"peak {peak / 1024 / 1024:.0f} MB, budget {MEMORY_MB}"


def test_the_whole_planned_backfill_fits_in_a_working_hour(
    corpus: dict[str, Records], run_gate: Any
) -> None:
    """Cleaning and returns for 40 instruments, extrapolated from the six recorded ones."""
    started = time.perf_counter()
    bars = 0
    for records in corpus.values():
        result = run_gate(records)
        returns.compute(
            [returns.PricePoint(b.session_date, b.close, b.adj_close) for b in result.clean]
        )
        bars += len(result.clean)
    per_symbol = (time.perf_counter() - started) / len(corpus)
    assert per_symbol * 40 < 3600, f"40 instruments would take {per_symbol * 40 / 60:.0f} minutes"
    assert bars >= 17_000
