"""A-NFR-01: a run over 40 instruments and 252 sessions in under 60 s.

The benchmark environment is generated (:mod:`qs_trading.demo.benchmark`) and shipped with
the bundled demo environments, so DEV serves it. These tests pin the file to its generator
and time the engine in memory over it with the costliest built-in strategy: momentum,
which ranks every instrument on each rebalance and checks the position cap on every other
session, with a linear cost model and volume slippage. The persisted run is timed in
``tests/db/test_performance_db.py``.
"""

import hashlib
import time
import uuid
from collections import Counter
from decimal import Decimal
from itertools import pairwise

import pytest

from qs_trading.adapters.file_environment import FileEnvironment
from qs_trading.demo import benchmark
from qs_trading.engine.core import Engine, LoggedEvent, RunSpec
from qs_trading.engine.runner import MemorySink, load_ticks, run_portfolio
from qs_trading.ports.market_environment import EnvironmentRef

BUDGET_SECONDS = 60.0
# The sha256 of the generated fixture; a change to the generator must update it on purpose
FIXTURE_SHA256 = "c4c3643f833e110c81d1e5a399f65158be9f1aeb82f773bf63299bed9dd20f80"

MOMENTUM = {"lookback": 60, "top_n": 10, "rebalance_every": 5, "max_position": "0.15"}
COST_MODEL = {"fixed": "1.00", "per_share": "0.005", "pct": "0.0005"}
SLIPPAGE_MODEL = {"kind": "volume", "bps": "10"}


def benchmark_spec(portfolio_id: uuid.UUID) -> RunSpec:
    return RunSpec(
        portfolio_id=portfolio_id,
        strategy_kind="momentum",
        strategy_params=MOMENTUM,
        initial_capital=Decimal("1000000"),
        cost_model=COST_MODEL,
        slippage_model=SLIPPAGE_MODEL,
        environment=EnvironmentRef("replay", benchmark.ENV_ID),
    )


def _assert_complete_chain(events: list[LoggedEvent]) -> None:
    types = Counter(event.type.value for event in events)
    assert events[0].type.value == "RUN_STARTED" and events[-1].type.value == "RUN_COMPLETED"
    assert types["TICK"] == types["VALUED"] == benchmark.SESSIONS
    assert types["ORDER_FILLED"] > 0
    assert [event.seq for event in events] == list(range(1, len(events) + 1))
    assert events[0].prev_hash is None
    for previous, current in pairwise(events):
        assert current.prev_hash == previous.hash


def test_the_bundled_benchmark_is_what_the_generator_writes() -> None:
    generated = benchmark.build()
    assert hashlib.sha256(generated).hexdigest() == FIXTURE_SHA256
    # A Windows checkout may turn LF into CRLF; the image is built from LF
    assert benchmark.PATH.read_bytes().replace(b"\r\n", b"\n") == generated
    assert benchmark.main(["--check"]) == 0


async def test_the_benchmark_has_40_instruments_over_252_sessions() -> None:
    environment = FileEnvironment(benchmark.PATH)
    assert environment.ref == EnvironmentRef("replay", benchmark.ENV_ID)
    page = await load_ticks(environment, await environment.activate())
    assert len(page) == benchmark.INSTRUMENTS * benchmark.SESSIONS
    assert len({tick.symbol for tick in page}) == benchmark.INSTRUMENTS
    assert len({tick.session for tick in page}) == benchmark.SESSIONS


async def test_the_pure_engine_runs_the_benchmark_well_inside_the_budget() -> None:
    environment = FileEnvironment(benchmark.PATH)
    fingerprint = await environment.activate()
    ticks = await load_ticks(environment, fingerprint)

    started = time.perf_counter()
    engine = Engine.prepare(benchmark_spec(uuid.UUID(int=40252)), fingerprint, ticks)
    results = engine.run()
    elapsed = time.perf_counter() - started

    events = [event for result in results for event in result.events]
    _assert_complete_chain(events)
    print(f"A-NFR-01 pure engine: {len(events)} events in {elapsed:.2f} s")
    assert elapsed < BUDGET_SECONDS


@pytest.mark.slow
async def test_a_full_run_over_the_file_environment_is_inside_the_budget() -> None:
    """``run_portfolio`` as the worker runs it, with the file adapter DEV uses and a sink
    in memory: activation, paging and the fingerprint check before every session."""
    environment = FileEnvironment(benchmark.PATH)
    sink = MemorySink()

    started = time.perf_counter()
    result = await run_portfolio(benchmark_spec(uuid.UUID(int=40253)), environment, sink)
    elapsed = time.perf_counter() - started

    _assert_complete_chain(sink.events)
    assert result.sessions == benchmark.SESSIONS
    assert result.final_hash == sink.events[-1].hash
    print(f"A-NFR-01 run_portfolio in memory: {len(sink.events)} events in {elapsed:.2f} s")
    assert elapsed < BUDGET_SECONDS
