"""Consumer contract tests of C1 and C2 (Lane A, guide section 14: JSON Schema validation
of real responses).

Every tick of both recorded fixtures (C3), every sample of ``contracts/events/samples`` and
every page the feeds serve through the HTTP adapters is validated against
``contracts/events/market.tick.v1.schema.json`` (C1, read in place). The rules the schema
cannot say (prices above zero, ``high >= low``) are checked by the adapter's own parser.
"""

import json
from pathlib import Path
from typing import Any

import pytest
from feed_support import (
    PATH_TICKS,
    REPLAY,
    REPLAY_ID,
    REPLAY_TICKS,
    RUN_ID,
    SAMPLES,
    SCHEMA,
    SYNTHETIC,
    ContractFeeds,
    load,
)
from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

from qs_trading.adapters.http_environment import (
    FeedContractViolation,
    ReplayFeed,
    SimulationPathFeed,
    parse_tick,
)
from qs_trading.engine.runner import load_ticks
from qs_trading.ports.market_environment import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, EnvironmentRef

# Invalid samples the adapter reads on purpose: it compares env_id with the environment it
# asked for rather than checking its form, and it accepts the stored name historical_replay.
ADAPTER_LENIENT = {"bad_uuid", "wrong_env_type"}
# Invalid samples the schema cannot refuse (contracts/README.md): only the adapter does.
SCHEMA_CANNOT_SAY = {"high_below_low", "zero_price"}


@pytest.fixture(scope="module")
def validator() -> Draft202012Validator:
    schema = load(SCHEMA)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _errors(validator: Draft202012Validator, item: dict[str, Any]) -> list[str]:
    return [error.message for error in validator.iter_errors(item)]


def test_the_schema_is_the_contract() -> None:
    schema = load(SCHEMA)
    assert schema["$id"] == "https://quantsim.local/contracts/events/market.tick.v1.schema.json"
    assert schema["title"] == "market.tick.v1"
    assert schema["properties"]["session_date"]["type"] == ["string", "null"]


def _sample(path: Path) -> tuple[dict[str, Any], EnvironmentRef]:
    item: dict[str, Any] = json.loads(path.read_bytes())
    if item.get("env_type") == "synthetic":
        return item, EnvironmentRef("simulation", item["env_id"], item.get("path_index") or 0)
    return item, EnvironmentRef("replay", item["env_id"])


@pytest.mark.parametrize("path", sorted((SAMPLES / "valid").glob("*.json")), ids=lambda p: p.stem)
def test_every_valid_sample_is_valid_and_read(validator: Draft202012Validator, path: Path) -> None:
    item, ref = _sample(path)
    assert _errors(validator, item) == []
    tick = parse_tick(item, ref, item["source_fingerprint"])
    assert (tick.seq, tick.symbol) == (item["seq"], item["symbol"])


@pytest.mark.parametrize("path", sorted((SAMPLES / "invalid").glob("*.json")), ids=lambda p: p.stem)
def test_every_invalid_sample_is_refused(validator: Draft202012Validator, path: Path) -> None:
    item, ref = _sample(path)
    assert bool(_errors(validator, item)) is (path.stem not in SCHEMA_CANNOT_SAY)
    if path.stem in ADAPTER_LENIENT:
        return
    with pytest.raises(FeedContractViolation):
        parse_tick(item, ref, item["source_fingerprint"])


# --- C3: the recorded fixtures ----------------------------------------------------------------


def test_every_replay_fixture_tick_is_valid(validator: Draft202012Validator) -> None:
    items = load(REPLAY)["items"]
    assert len(items) == REPLAY_TICKS
    for item in items:
        assert _errors(validator, item) == [], item["seq"]
        parse_tick(item, EnvironmentRef("replay", REPLAY_ID), item["source_fingerprint"])


def test_every_synthetic_fixture_tick_is_valid(validator: Draft202012Validator) -> None:
    paths = load(SYNTHETIC)["paths"]
    assert [p["path_index"] for p in paths] == [0, 1, 2]
    for path in paths:
        assert len(path["items"]) == PATH_TICKS
        ref = EnvironmentRef("simulation", RUN_ID, path["path_index"])
        for item in path["items"]:
            assert _errors(validator, item) == [], (path["path_index"], item["seq"])
            parse_tick(item, ref, item["source_fingerprint"])


# --- C2: the pages the feeds serve ----------------------------------------------------------


def _validate_pages(validator: Draft202012Validator, feeds: ContractFeeds) -> int:
    assert feeds.pages
    ticks = 0
    for page in feeds.pages:
        assert set(page) == {"items", "next_after_seq"}
        assert len(page["items"]) <= MAX_PAGE_SIZE
        for item in page["items"]:
            assert _errors(validator, item) == [], item["seq"]
        ticks += len(page["items"])
    return ticks


@pytest.mark.parametrize("page_size", [DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE])
async def test_every_replay_page_served_is_valid(
    validator: Draft202012Validator, page_size: int
) -> None:
    feeds = ContractFeeds()
    feed = ReplayFeed(feeds.market_client(), REPLAY_ID)
    fingerprint = await feed.activate()
    ticks = await load_ticks(feed, fingerprint, page_size=page_size)
    assert len(ticks) == REPLAY_TICKS
    assert _validate_pages(validator, feeds) == REPLAY_TICKS


@pytest.mark.parametrize("path_index", [0, 1, 2])
async def test_every_synthetic_page_served_is_valid(
    validator: Draft202012Validator, path_index: int
) -> None:
    feeds = ContractFeeds(detail_fingerprint=False)
    feed = SimulationPathFeed(feeds.simulation_client(), RUN_ID, path_index)
    fingerprint = await feed.activate()  # reads the first page (one tick) for the fingerprint
    ticks = await load_ticks(feed, fingerprint, page_size=50)
    assert len(ticks) == PATH_TICKS
    assert _validate_pages(validator, feeds) == 1 + PATH_TICKS


# --- shapes the contract allows -------------------------------------------------------------


def _replay_tick() -> dict[str, Any]:
    item: dict[str, Any] = load(REPLAY)["items"][0]
    return item


def test_a_replay_tick_without_the_optional_fields_is_valid(
    validator: Draft202012Validator,
) -> None:
    item = _replay_tick()
    for name in ("session_date", "path_index", "scenario"):
        del item[name]
    assert _errors(validator, item) == []
    parse_tick(item, EnvironmentRef("replay", REPLAY_ID), item["source_fingerprint"])


def test_an_unknown_field_is_valid_and_ignored(validator: Draft202012Validator) -> None:
    item = _replay_tick()
    item["share_class"] = "A"
    assert _errors(validator, item) == []
    parse_tick(item, EnvironmentRef("replay", REPLAY_ID), item["source_fingerprint"])


def test_a_null_session_date_is_valid_and_read(validator: Draft202012Validator) -> None:
    item = _replay_tick()
    item["session_date"] = None
    assert _errors(validator, item) == []
    tick = parse_tick(item, EnvironmentRef("replay", REPLAY_ID), item["source_fingerprint"])
    assert tick.seq == 1


@pytest.mark.parametrize("value", ["2020-1-2", "2020-02-30", 20200102, "yesterday"])
def test_a_malformed_session_date_is_refused(
    validator: Draft202012Validator, value: object
) -> None:
    item = _replay_tick()
    item["session_date"] = value
    if value != "2020-02-30":  # the pattern cannot tell a calendar date
        assert _errors(validator, item)
    with pytest.raises(FeedContractViolation, match="session_date"):
        parse_tick(item, EnvironmentRef("replay", REPLAY_ID), item["source_fingerprint"])


@pytest.mark.parametrize(
    ("field", "value"),
    [("close", 72.27), ("close", "7.2e1"), ("open", "-1"), ("ts", "2020-01-02T21:00:00")],
)
def test_what_the_schema_refuses_the_adapter_refuses(
    validator: Draft202012Validator, field: str, value: object
) -> None:
    item = _replay_tick()
    item[field] = value
    assert _errors(validator, item)
    with pytest.raises(FeedContractViolation):
        parse_tick(item, EnvironmentRef("replay", REPLAY_ID), item["source_fingerprint"])
