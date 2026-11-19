"""The file market environment (A14): paging, fingerprint, and the tick rules it checks."""

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from qs_trading.adapters.file_environment import (
    FileEnvironment,
    FixtureError,
    file_environments,
    fingerprint_of,
)
from qs_trading.ports.market_environment import (
    EnvironmentRef,
    FingerprintChanged,
    MarketEnvironment,
)

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/environments/two_symbols_10_sessions.json"
ENV_ID = "5d0c6c1e-7a14-4a14-8a14-000000000001"


def _document() -> dict[str, Any]:
    document: dict[str, Any] = json.loads(FIXTURE.read_text())
    return document


def _write(path: Path, document: dict[str, Any]) -> Path:
    path.write_text(json.dumps(document))
    return path


def test_it_reads_the_contract_fixture_shape() -> None:
    environment: MarketEnvironment = FileEnvironment(FIXTURE)
    assert environment.ref == EnvironmentRef("replay", ENV_ID)


async def test_the_fingerprint_is_the_sha256_of_the_file() -> None:
    environment = FileEnvironment(FIXTURE)
    expected = "sha256:" + hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
    assert await environment.fingerprint() == expected
    assert await environment.activate() == expected
    assert environment.frozen_fingerprint == expected


async def test_ticks_come_in_pages_by_after_seq() -> None:
    environment = FileEnvironment(FIXTURE)
    fingerprint = await environment.activate()
    seen: list[int] = []
    after_seq, pages = 0, 0
    while True:
        page = await environment.ticks(after_seq, limit=5)
        assert page.fingerprint == fingerprint
        assert len(page.items) <= 5
        seen.extend(t.seq for t in page.items)
        pages += 1
        if page.next_after_seq is None:
            break
        assert page.next_after_seq == page.items[-1].seq
        after_seq = page.next_after_seq
    assert seen == list(range(1, 20))
    assert pages == 4
    tail = await environment.ticks(19)
    assert list(tail.items) == []
    assert tail.next_after_seq is None


async def test_a_page_that_ends_exactly_on_the_last_tick_is_the_last_page() -> None:
    page = await FileEnvironment(FIXTURE).ticks(0, limit=19)
    assert len(page.items) == 19 and page.next_after_seq is None


async def test_ticks_carry_the_bar_and_session() -> None:
    page = await FileEnvironment(FIXTURE).ticks(0, limit=2)
    first = page.items[0]
    assert (first.seq, first.session, first.symbol) == (1, 0, "AAA")
    assert str(first.open) == "100" and str(first.volume) == "1000000"
    assert first.ts.isoformat() == "2026-01-05T21:00:00+00:00"


async def test_session_3_has_no_bar_for_bbb() -> None:
    page = await FileEnvironment(FIXTURE).ticks(0, limit=100)
    assert [t.symbol for t in page.items if t.session == 3] == ["AAA"]


@pytest.mark.parametrize(("after_seq", "limit"), [(-1, 10), (0, 0), (0, 2001)])
async def test_bad_paging_arguments_are_refused(after_seq: int, limit: int) -> None:
    with pytest.raises(ValueError):
        await FileEnvironment(FIXTURE).ticks(after_seq, limit)


async def test_a_change_after_activation_raises_fingerprint_changed(tmp_path: Path) -> None:
    path = _write(tmp_path / "env.json", _document())
    environment = FileEnvironment(path)
    frozen = await environment.activate()
    await environment.ticks(0, 5)
    document = _document()
    document["items"][4]["close"] = "102.5"
    _write(path, document)
    assert await environment.fingerprint() == fingerprint_of(path.read_bytes()) != frozen
    with pytest.raises(FingerprintChanged) as raised:
        await environment.ticks(5, 5)
    assert raised.value.expected == frozen


async def test_before_activation_a_change_is_simply_served(tmp_path: Path) -> None:
    path = _write(tmp_path / "env.json", _document())
    environment = FileEnvironment(path)
    document = _document()
    document["items"][0]["close"] = "100.5"
    _write(path, document)
    page = await environment.ticks(0, 1)
    assert str(page.items[0].close) == "100.5"


def _broken(tmp_path: Path, change: Any) -> Path:
    document = _document()
    change(document)
    return _write(tmp_path / "broken.json", document)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda d: d["items"].pop(3), "without gaps"),
        (lambda d: d["items"][1].update(symbol="AAA"), r"\(session, symbol\)"),
        (lambda d: d["items"][0].update(open=100.5), "decimal string"),
        (lambda d: d["items"][0].update(low="0"), "above zero"),
        (lambda d: d["items"][0].update(high="98"), "high is below low"),
        (lambda d: d["items"][0].update(ts="2026-01-05T21:00:00"), "zone"),
        (lambda d: d["environment"].update(type="unknown"), "known type"),
        (lambda d: d.pop("items"), "items"),
    ],
)
def test_broken_fixtures_are_refused(tmp_path: Path, change: Any, message: str) -> None:
    with pytest.raises(FixtureError, match=message):
        FileEnvironment(_broken(tmp_path, change))


def test_a_missing_file_is_a_fixture_error(tmp_path: Path) -> None:
    with pytest.raises(FixtureError, match="cannot read"):
        FileEnvironment(tmp_path / "absent.json")


def test_a_synthetic_fixture_is_a_simulation_path(tmp_path: Path) -> None:
    document = _document()
    document["environment"]["type"] = "synthetic"
    for item in document["items"]:
        item["path_index"] = 2
    environment = FileEnvironment(_write(tmp_path / "sim.json", document))
    assert environment.ref == EnvironmentRef("simulation", ENV_ID, 2)


def test_the_directory_factory_opens_by_environment_id(tmp_path: Path) -> None:
    _write(tmp_path / f"{ENV_ID}.json", _document())
    open_environment = file_environments(tmp_path)
    assert open_environment(EnvironmentRef("replay", ENV_ID)).ref.env_id == ENV_ID
    other = "00000000-0000-4000-8000-0000000000ff"
    _write(tmp_path / f"{other}.json", _document())
    with pytest.raises(FixtureError, match="describes"):
        open_environment(EnvironmentRef("replay", other))
