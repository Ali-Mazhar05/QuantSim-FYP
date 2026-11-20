"""Consumer contract tests of C1 and C2 (Lane A, guide section 14: JSON Schema validation
of real responses).

Every tick of both recorded fixtures (C3) and every page the feeds serve through the HTTP
adapters is validated against ``market.tick.v1.schema.json``, a byte-identical copy of the
schema in #80 (``tests/fixtures/contracts/README.md``). The rules the schema cannot say
(prices above zero, ``high >= low``) are checked by the adapter's own parser.
"""

import hashlib
from typing import Any

import pytest
from feed_support import (
    PATH_TICKS,
    REPLAY,
    REPLAY_ID,
    REPLAY_TICKS,
    RUN_ID,
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

SCHEMA_SHA256 = "4a46a06de1df584b8554c936de7c89726cfe8bff9bd0c1a28c3f340ac1e65392"


@pytest.fixture(scope="module")
def validator() -> Draft202012Validator:
    schema = load(SCHEMA)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _errors(validator: Draft202012Validator, item: dict[str, Any]) -> list[str]:
    return [error.message for error in validator.iter_errors(item)]


def test_the_schema_is_the_one_in_the_contract_pull_request() -> None:
    schema = load(SCHEMA)
    assert schema["$id"] == "https://quantsim.local/contracts/events/market.tick.v1.schema.json"
    assert schema["title"] == "market.tick.v1"
    assert hashlib.sha256(SCHEMA.read_bytes()).hexdigest() == SCHEMA_SHA256


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


@pytest.mark.xfail(
    strict=True,
    reason="#80 review: session_date must be nullable (the feed's model is date | None and "
    "a synthetic tick has none); the schema in #80 still says type string",
)
def test_a_null_session_date_is_valid(validator: Draft202012Validator) -> None:
    item = _replay_tick()
    item["session_date"] = None
    assert _errors(validator, item) == []


def test_the_adapter_accepts_a_null_session_date() -> None:
    item = _replay_tick()
    item["session_date"] = None
    tick = parse_tick(item, EnvironmentRef("replay", REPLAY_ID), item["source_fingerprint"])
    assert tick.seq == 1


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
