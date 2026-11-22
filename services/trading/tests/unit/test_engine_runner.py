"""The engine run loop on the file adapter with an in-memory sink: a full run equals the
pure core, a crash then resume gives the identical log (A-FR-13), and market data that
changes mid-run stops the engine."""

import json
import shutil
import uuid
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from qs_template import Database
from qs_trading.adapters.file_environment import FileEnvironment
from qs_trading.engine.core import Engine, ResumeMismatch, RunSpec
from qs_trading.engine.runner import MemorySink, load_ticks, run_portfolio
from qs_trading.jobs import (
    ENGINE_RUN,
    build_handlers,
    engine_run_key,
    no_environments,
)
from qs_trading.ports.market_environment import (
    EnvironmentRef,
    FingerprintChanged,
    MarketEnvironmentError,
)
from qs_trading.settings import TradingSettings

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/environments/two_symbols_10_sessions.json"
PORTFOLIO = uuid.UUID("0a140000-0000-4000-8000-000000000002")
REF = EnvironmentRef("replay", "5d0c6c1e-7a14-4a14-8a14-000000000001")


class Crash(Exception):
    """Stands in for a killed worker."""


def _spec(**changes: object) -> RunSpec:
    spec = RunSpec(
        portfolio_id=PORTFOLIO,
        strategy_kind="momentum",
        strategy_params={"lookback": 2, "top_n": 1, "rebalance_every": 2, "max_position": "0.9"},
        initial_capital=Decimal("10000"),
        cost_model={"fixed": "1.00", "per_share": "0.01", "pct": "0.0005"},
        slippage_model={"kind": "volume", "bps": "20"},
        environment=REF,
    )
    return replace(spec, **changes)  # type: ignore[arg-type]


async def _uninterrupted() -> list[str]:
    environment = FileEnvironment(FIXTURE)
    fingerprint = await environment.activate()
    engine = Engine.prepare(_spec(), fingerprint, await load_ticks(environment, fingerprint))
    return [event.hash for result in engine.run() for event in result.events]


async def test_a_run_commits_every_session_and_equals_the_pure_core() -> None:
    sink = MemorySink()
    done: list[float] = []

    async def progress(share: float) -> None:
        done.append(share)

    result = await run_portfolio(_spec(), FileEnvironment(FIXTURE), sink, progress=progress)
    assert [e.hash for e in sink.events] == await _uninterrupted()
    assert sink.sessions_committed == 10
    assert sum(e.type.value == "ORDER_FILLED" for e in sink.events) == 6
    assert done == [(i + 1) / 10 for i in range(10)]
    assert (result.sessions, result.resumed_at_session) == (10, 0)
    assert (result.final_seq, result.final_hash) == (sink.events[-1].seq, sink.events[-1].hash)
    assert result.to_json()["final_value"] == str(result.final_value)
    assert sink.fingerprint == result.source_fingerprint


@pytest.mark.parametrize("crash_after", [1, 4, 9])
async def test_a_crashed_run_resumes_to_the_identical_log(crash_after: int) -> None:
    sink = MemorySink()

    async def killed(share: float) -> None:
        if round(share * 10) == crash_after:
            raise Crash

    with pytest.raises(Crash):
        await run_portfolio(_spec(), FileEnvironment(FIXTURE), sink, progress=killed)
    assert sink.sessions_committed == crash_after
    result = await run_portfolio(_spec(), FileEnvironment(FIXTURE), sink)
    assert result.resumed_at_session == crash_after
    assert [e.hash for e in sink.events] == await _uninterrupted()
    assert [e.seq for e in sink.events] == list(range(1, len(sink.events) + 1))


async def test_resuming_a_complete_run_writes_nothing() -> None:
    sink = MemorySink()
    first = await run_portfolio(_spec(), FileEnvironment(FIXTURE), sink)
    again = await run_portfolio(_spec(), FileEnvironment(FIXTURE), sink)
    assert again.final_hash == first.final_hash
    assert again.resumed_at_session == 10
    assert sink.sessions_committed == 10


async def test_resuming_with_a_changed_spec_is_refused() -> None:
    sink = MemorySink()

    async def killed(share: float) -> None:
        if share >= 0.5:
            raise Crash

    with pytest.raises(Crash):
        await run_portfolio(_spec(), FileEnvironment(FIXTURE), sink, progress=killed)
    changed = _spec(cost_model={"fixed": "2.00"})
    with pytest.raises(ResumeMismatch):
        await run_portfolio(changed, FileEnvironment(FIXTURE), sink)


async def test_a_fixture_changed_mid_run_stops_the_engine(tmp_path: Path) -> None:
    path = tmp_path / "env.json"
    shutil.copyfile(FIXTURE, path)
    sink = MemorySink()

    async def edit_after_three(share: float) -> None:
        if round(share * 10) == 3:
            document = json.loads(path.read_text())
            document["items"][-1]["close"] = "54.5"
            path.write_text(json.dumps(document))

    with pytest.raises(FingerprintChanged):
        await run_portfolio(_spec(), FileEnvironment(path), sink, progress=edit_after_three)
    assert sink.sessions_committed == 3
    # The portfolio stays bound to the data it started on
    with pytest.raises(FingerprintChanged):
        await run_portfolio(_spec(), FileEnvironment(path), sink)


async def test_the_environment_must_be_the_one_the_portfolio_is_bound_to() -> None:
    other = _spec(environment=EnvironmentRef("replay", str(uuid.UUID(int=9))))
    with pytest.raises(ValueError, match="wants"):
        await run_portfolio(other, FileEnvironment(FIXTURE), MemorySink())


def test_job_keys_and_handlers(settings: TradingSettings) -> None:
    assert engine_run_key(PORTFOLIO) == f"engine.run:{PORTFOLIO}"
    assert engine_run_key(PORTFOLIO, "abc") == f"engine.run:{PORTFOLIO}:abc"
    assert set(build_handlers(Database(settings))) == {ENGINE_RUN}
    with pytest.raises(MarketEnvironmentError, match="no market adapter"):
        no_environments(REF)
