"""Lane B's recorded contract fixtures (C3) on the file adapter: the replay of 2020 and the
synthetic run of three paths load, page within the contract's limit (ADR 01, DL-008) and
report the provider's declared fingerprint (ADR 08), so a run over the file and a run over
the HTTP feed of the same ticks record the same one.

The two files are copied byte for byte from ``contracts/fixtures/`` and must not be edited.
"""

import json
import shutil
import uuid
from decimal import Decimal
from itertools import pairwise
from pathlib import Path
from typing import Any

import pytest

from qs_trading.adapters.file_environment import (
    FileEnvironment,
    FixtureChanged,
    FixtureError,
    file_environments,
    fingerprint_of,
)
from qs_trading.domain.events import RunStartedV1
from qs_trading.domain.hashing import event_hash
from qs_trading.engine.core import Engine, RunSpec
from qs_trading.engine.runner import load_ticks
from qs_trading.ports.market_environment import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    EnvironmentRef,
    FingerprintChanged,
)

CONTRACTS = Path(__file__).resolve().parents[1] / "fixtures/contracts"
REPLAY = CONTRACTS / "replay_ticks_2020.json"
SYNTHETIC = CONTRACTS / "synthetic_ticks.json"

REPLAY_ID = "c74eb808-acc6-5fc0-9400-7faa69480261"
REPLAY_FINGERPRINT = "xxh3:2f5521859c9b7beb06802a3df29ef9c3"
REPLAY_TICKS = 1265
RUN_ID = "91fc2771-788d-5a18-99f9-b724c10ea8c8"
RUN_FINGERPRINT = "xxh3:23276fd99c1dff797c94878a6340a06a"
PATH_TICKS = 180  # 60 steps of AAPL, MSFT and NVDA


def _load(path: Path) -> dict[str, Any]:
    document: dict[str, Any] = json.loads(path.read_bytes())
    return document


def _write(path: Path, document: dict[str, Any]) -> Path:
    path.write_text(json.dumps(document))
    return path


def test_the_page_limits_follow_the_contract() -> None:
    assert (DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE) == (500, 2000)


# --- the replay ----------------------------------------------------------------------------


async def test_the_replay_fixture_reports_its_declared_fingerprint() -> None:
    environment = FileEnvironment(REPLAY)
    assert environment.ref == EnvironmentRef("replay", REPLAY_ID)
    assert environment.median_path_index is None
    assert await environment.fingerprint() == REPLAY_FINGERPRINT
    assert await environment.activate() == REPLAY_FINGERPRINT
    assert environment.frozen_fingerprint == REPLAY_FINGERPRINT


@pytest.mark.parametrize(("limit", "pages"), [(DEFAULT_PAGE_SIZE, 3), (MAX_PAGE_SIZE, 1)])
async def test_the_replay_fixture_pages_within_the_limit(limit: int, pages: int) -> None:
    environment = FileEnvironment(REPLAY)
    await environment.activate()
    seqs: list[int] = []
    after_seq, served = 0, 0
    while True:
        page = await environment.ticks(after_seq, limit)
        assert page.fingerprint == REPLAY_FINGERPRINT
        assert len(page.items) <= limit
        seqs.extend(t.seq for t in page.items)
        served += 1
        if page.next_after_seq is None:
            break
        after_seq = page.next_after_seq
    assert seqs == list(range(1, REPLAY_TICKS + 1))
    assert served == pages


async def test_the_default_page_is_500_ticks() -> None:
    page = await FileEnvironment(REPLAY).ticks()
    assert len(page.items) == DEFAULT_PAGE_SIZE and page.next_after_seq == DEFAULT_PAGE_SIZE


async def test_the_replay_fixture_ticks_are_the_recorded_bars() -> None:
    page = await FileEnvironment(REPLAY).ticks(0, 5)
    first = page.items[0]
    assert (first.seq, first.session, first.symbol) == (1, 0, "AAPL")
    assert first.ts.isoformat() == "2020-01-02T21:00:00+00:00"
    assert first.close == Decimal("72.2762984036")
    assert [t.symbol for t in page.items] == ["AAPL", "KO", "MSFT", "NVDA", "TSLA"]


@pytest.mark.parametrize("limit", [MAX_PAGE_SIZE + 1, 5000])
async def test_a_page_above_2000_is_refused(limit: int) -> None:
    with pytest.raises(ValueError, match="2000"):
        await FileEnvironment(REPLAY).ticks(0, limit)


def test_the_replay_fixture_takes_no_path_index() -> None:
    with pytest.raises(FixtureError, match="no paths"):
        FileEnvironment(REPLAY, path_index=0)


def test_a_tick_with_another_fingerprint_is_refused(tmp_path: Path) -> None:
    document = _load(REPLAY)
    document["items"][7]["source_fingerprint"] = "xxh3:00000000000000000000000000000000"
    with pytest.raises(FixtureError, match="tick 8 carries source_fingerprint"):
        FileEnvironment(_write(tmp_path / "replay.json", document))


async def test_a_byte_change_after_activation_is_noticed_under_the_same_declared_value(
    tmp_path: Path,
) -> None:
    path = tmp_path / "replay.json"
    shutil.copyfile(REPLAY, path)
    environment = FileEnvironment(path)
    assert await environment.activate() == REPLAY_FINGERPRINT
    await environment.ticks(0, 10)
    frozen_bytes = fingerprint_of(path.read_bytes())
    document = _load(REPLAY)
    document["items"][20]["close"] = "123.4500000000"  # a restated price, same declared value
    _write(path, document)
    changed_bytes = fingerprint_of(path.read_bytes())
    for read in (environment.fingerprint(), environment.ticks(10, 10)):
        with pytest.raises(FixtureChanged) as raised:
            await read
        assert isinstance(raised.value, FingerprintChanged)
        assert raised.value.expected == raised.value.actual == REPLAY_FINGERPRINT
        assert str(raised.value) == (
            f"the fixture {path} changed after activation: it still declares"
            f" {REPLAY_FINGERPRINT}, but its bytes went from {frozen_bytes} to {changed_bytes}"
        )


async def test_a_changed_declared_value_after_activation_is_fingerprint_changed(
    tmp_path: Path,
) -> None:
    path = tmp_path / "replay.json"
    shutil.copyfile(REPLAY, path)
    environment = FileEnvironment(path)
    await environment.activate()
    restated = "xxh3:ffffffffffffffffffffffffffffffff"
    document = _load(REPLAY)
    document["environment"]["source_fingerprint"] = restated
    for item in document["items"]:
        item["source_fingerprint"] = restated
    _write(path, document)
    assert await environment.fingerprint() == restated
    with pytest.raises(FingerprintChanged) as raised:
        await environment.ticks(0, 10)
    assert (raised.value.expected, raised.value.actual) == (REPLAY_FINGERPRINT, restated)


async def test_without_a_declared_value_the_fingerprint_is_the_file_bytes(
    tmp_path: Path,
) -> None:
    document = _load(REPLAY)
    del document["environment"]["source_fingerprint"]
    for item in document["items"]:
        del item["source_fingerprint"]
    path = _write(tmp_path / "replay.json", document)
    assert await FileEnvironment(path).activate() == fingerprint_of(path.read_bytes())


async def test_a_buy_and_hold_run_over_the_replay_fixture_records_the_xxh3_fingerprint() -> None:
    environment = FileEnvironment(REPLAY)
    fingerprint = await environment.activate()
    ticks = await load_ticks(environment, fingerprint)
    assert len(ticks) == REPLAY_TICKS
    portfolio = uuid.UUID("0a140000-0000-4000-8000-0000000000c1")
    spec = RunSpec(
        portfolio_id=portfolio,
        strategy_kind="buy_and_hold",
        strategy_params={},
        initial_capital=Decimal("100000"),
        cost_model={"fixed": "1.00", "per_share": "0.005", "pct": "0.0005"},
        slippage_model={"kind": "fixed_bps", "bps": "5"},
        environment=EnvironmentRef("replay", REPLAY_ID),
    )
    engine = Engine.prepare(spec, fingerprint, ticks)
    events = [event for result in engine.run() for event in result.events]
    assert len(engine.sessions) == 253
    first = events[0]
    assert isinstance(first.payload, RunStartedV1)
    assert first.payload.source_fingerprint == REPLAY_FINGERPRINT
    assert (first.payload.env_type, first.payload.env_id) == ("replay", REPLAY_ID)
    assert events[-1].type.value == "RUN_COMPLETED"
    assert any(event.type.value == "ORDER_FILLED" for event in events)
    assert [event.seq for event in events] == list(range(1, len(events) + 1))
    assert first.prev_hash is None
    for previous, current in pairwise(events):
        assert current.prev_hash == previous.hash
    for event in events:
        assert event.hash == event_hash(
            event.prev_hash,
            portfolio_id=portfolio,
            seq=event.seq,
            event_type=event.type,
            version=event.version,
            payload=event.payload_json,
            event_time=event.event_time,
        )


# --- the synthetic run ---------------------------------------------------------------------


@pytest.mark.parametrize("path_index", [0, 1, 2])
async def test_each_path_of_the_synthetic_fixture_loads(path_index: int) -> None:
    environment = FileEnvironment(SYNTHETIC, path_index=path_index)
    assert environment.ref == EnvironmentRef("simulation", RUN_ID, path_index)
    assert environment.median_path_index == 2
    assert await environment.activate() == RUN_FINGERPRINT
    ticks = await load_ticks(environment, RUN_FINGERPRINT)
    assert [t.seq for t in ticks] == list(range(1, PATH_TICKS + 1))
    assert {t.symbol for t in ticks} == {"AAPL", "MSFT", "NVDA"}
    assert all(t.open == t.high == t.low == t.close and t.volume == 0 for t in ticks)


async def test_the_paths_of_the_synthetic_fixture_differ() -> None:
    closes = [
        [t.close for t in (await FileEnvironment(SYNTHETIC, path_index=i).ticks(0, 200)).items]
        for i in range(3)
    ]
    assert closes[0] != closes[1] != closes[2]


def test_a_synthetic_run_fixture_needs_a_path_index() -> None:
    with pytest.raises(FixtureError, match="pass a path_index"):
        FileEnvironment(SYNTHETIC)


def test_a_path_the_run_does_not_hold_is_refused() -> None:
    with pytest.raises(FixtureError, match="exactly one path 3"):
        FileEnvironment(SYNTHETIC, path_index=3)


def test_a_synthetic_tick_with_another_fingerprint_is_refused(tmp_path: Path) -> None:
    document = _load(SYNTHETIC)
    document["paths"][1]["items"][0]["source_fingerprint"] = "xxh3:1"
    path = _write(tmp_path / "run.json", document)
    FileEnvironment(path, path_index=0)  # path 0 is untouched
    with pytest.raises(FixtureError, match="carries source_fingerprint"):
        FileEnvironment(path, path_index=1)


def test_a_tick_on_another_path_is_refused(tmp_path: Path) -> None:
    document = _load(SYNTHETIC)
    document["paths"][0]["items"][5]["path_index"] = 1
    with pytest.raises(FixtureError, match="not on path 0"):
        FileEnvironment(_write(tmp_path / "run.json", document), path_index=0)


def test_the_directory_factory_opens_the_contract_fixtures(tmp_path: Path) -> None:
    shutil.copyfile(REPLAY, tmp_path / f"{REPLAY_ID}.json")
    shutil.copyfile(SYNTHETIC, tmp_path / f"{RUN_ID}.json")
    open_environment = file_environments(tmp_path)
    assert open_environment(EnvironmentRef("replay", REPLAY_ID)).ref.env_id == REPLAY_ID
    median = open_environment(EnvironmentRef("simulation", RUN_ID, 2))
    assert median.ref == EnvironmentRef("simulation", RUN_ID, 2)
    assert median.median_path_index == 2
    with pytest.raises(FixtureError, match="pass a path_index"):
        open_environment(EnvironmentRef("replay", RUN_ID))


def test_the_directory_factory_prefers_a_per_path_file(tmp_path: Path) -> None:
    shutil.copyfile(SYNTHETIC, tmp_path / f"{RUN_ID}.json")
    run = _load(SYNTHETIC)
    single = {
        "environment": {"id": RUN_ID, "type": "synthetic", "path_index": 1},
        "items": run["paths"][1]["items"][:6],
    }
    _write(tmp_path / f"{RUN_ID}.path-1.json", single)
    open_environment = file_environments(tmp_path)
    per_path = open_environment(EnvironmentRef("simulation", RUN_ID, 1))
    assert per_path.path.name == f"{RUN_ID}.path-1.json"
    assert per_path.median_path_index is None
    assert open_environment(EnvironmentRef("simulation", RUN_ID, 0)).path.name == f"{RUN_ID}.json"
