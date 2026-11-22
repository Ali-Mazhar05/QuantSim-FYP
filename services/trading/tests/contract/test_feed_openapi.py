"""Consumer contract tests of C2 (Lane A): the market feed routes as the market service's
OpenAPI document (``frontend/src/services/generated/market/openapi.json``) and
``contracts/README.md`` section 3 define them.

(a) What the HTTP adapter tests are served conforms: every page to ``TickPage`` (and each
tick to ``Tick``), every environment detail to ``EnvironmentOut``, the 422
``missing-adjusted-prices`` problem to the shape in the README. (b) The adapter reads every
field those models define: each tick field is checked (a wrong type is refused), the
nullable ``session_date``, ``path_index`` and ``scenario`` are read as null, and the
detail's nullable ``source_fingerprint``, ``activated_at`` and ``activated_by`` are read in
both states. The requests go through the worker's own client (K3's ``ServiceClient``).
"""

from datetime import UTC, datetime
from typing import Any

import pytest
from feed_support import (
    ACTIVATED_AT,
    ACTIVATED_BY,
    MARKET_OPENAPI,
    REPLAY,
    REPLAY_FINGERPRINT,
    REPLAY_ID,
    REPLAY_TICKS,
    ContractFeeds,
    load,
)
from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

from qs_trading.adapters.http_environment import (
    EnvironmentNotActive,
    FeedContractViolation,
    ReplayFeed,
    parse_tick,
)
from qs_trading.engine.runner import load_ticks
from qs_trading.jobs import is_permanent
from qs_trading.ports.market_environment import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    EnvironmentRef,
    MissingAdjustedPrices,
)

TICKS_ROUTE = "/api/market/environments/{environment_id}/ticks"
DETAIL_ROUTE = "/api/market/environments/{environment_id}"
MISSING_ADJUSTED_PRICES = "urn:quantsim:problem:missing-adjusted-prices"
TICK_FIELDS = [
    "close",
    "env_id",
    "env_type",
    "high",
    "instrument_id",
    "low",
    "open",
    "path_index",
    "scenario",
    "seq",
    "session",
    "session_date",
    "source_fingerprint",
    "symbol",
    "ts",
    "volume",
]


@pytest.fixture(scope="module")
def openapi() -> dict[str, Any]:
    return load(MARKET_OPENAPI)


def _model(openapi: dict[str, Any], name: str) -> dict[str, Any]:
    model: dict[str, Any] = openapi["components"]["schemas"][name]
    return model


def _validator(openapi: dict[str, Any], name: str) -> Draft202012Validator:
    """A validator of one OpenAPI 3.1 component (JSON Schema 2020-12)."""
    schema = {"$ref": f"#/components/schemas/{name}", "components": openapi["components"]}
    return Draft202012Validator(schema)


def _errors(validator: Draft202012Validator, document: Any) -> list[str]:
    return [error.message for error in validator.iter_errors(document)]


def _nullable(prop: dict[str, Any]) -> bool:
    return any(option.get("type") == "null" for option in prop.get("anyOf", []))


def _replay_tick() -> dict[str, Any]:
    item: dict[str, Any] = load(REPLAY)["items"][0]
    return item


# --- the routes -----------------------------------------------------------------------------


def test_the_ticks_route_pages_as_the_port_does(openapi: dict[str, Any]) -> None:
    get = openapi["paths"][TICKS_ROUTE]["get"]
    params = {p["name"]: p["schema"] for p in get["parameters"] if p["in"] == "query"}
    assert params["after_seq"]["minimum"] == 0
    assert params["limit"]["default"] == DEFAULT_PAGE_SIZE
    assert (params["limit"]["minimum"], params["limit"]["maximum"]) == (1, MAX_PAGE_SIZE)
    ok = get["responses"]["200"]
    assert ok["content"]["application/json"]["schema"]["$ref"].endswith("/TickPage")
    assert "X-Source-Fingerprint" in ok["headers"]
    assert "missing-adjusted-prices" in get["responses"]["422"]["description"]


def test_the_detail_route_serves_the_environment(openapi: dict[str, Any]) -> None:
    ok = openapi["paths"][DETAIL_ROUTE]["get"]["responses"]["200"]
    assert ok["content"]["application/json"]["schema"]["$ref"].endswith("/EnvironmentOut")
    detail = _model(openapi, "EnvironmentOut")["properties"]
    for name in ("source_fingerprint", "activated_at", "activated_by"):
        assert _nullable(detail[name]), name


# --- (a) what the tests are served conforms ---------------------------------------------------


@pytest.mark.parametrize("page_size", [DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, 97])
async def test_every_page_served_is_a_tick_page(openapi: dict[str, Any], page_size: int) -> None:
    feeds = ContractFeeds()
    feed = ReplayFeed(feeds.market_client(), REPLAY_ID)
    assert len(await load_ticks(feed, await feed.activate(), page_size=page_size)) == REPLAY_TICKS
    validator = _validator(openapi, "TickPage")
    for page in feeds.pages:
        assert _errors(validator, page) == []


@pytest.mark.parametrize("activated", [True, False])
async def test_every_detail_served_is_an_environment(
    openapi: dict[str, Any], activated: bool
) -> None:
    feeds = ContractFeeds(detail_fingerprint=activated)
    await ReplayFeed(feeds.market_client(), REPLAY_ID).activate()
    (detail,) = feeds.details
    assert _errors(_validator(openapi, "EnvironmentOut"), detail) == []
    assert (detail["source_fingerprint"] is None) is (not activated)


async def test_the_missing_adjusted_prices_problem_is_the_contract_one() -> None:
    feeds = ContractFeeds()
    feeds.missing = {"AAPL": 3, "KO": 1}
    with pytest.raises(MissingAdjustedPrices):
        await ReplayFeed(feeds.market_client(), REPLAY_ID).ticks(0, 10)
    (served,) = feeds.problems
    # contracts/README.md section 3: a problem+json with the bar count per symbol
    assert served["type"] == MISSING_ADJUSTED_PRICES
    assert served["status"] == 422
    assert {"type", "title", "status", "detail", "missing"} <= set(served)
    assert all(isinstance(n, int) and n >= 0 for n in served["missing"].values())


# --- (b) the adapter reads every field ------------------------------------------------------


def _wrong(name: str, prop: dict[str, Any]) -> object:
    """A value of the wrong JSON type for a tick field."""
    if prop.get("type") == "integer" or name == "path_index":
        return "not-a-number"
    return 12345


def test_the_fixture_tick_has_every_field_of_the_model(openapi: dict[str, Any]) -> None:
    assert set(_model(openapi, "Tick")["properties"]) <= set(_replay_tick())


def test_the_checked_fields_are_the_model(openapi: dict[str, Any]) -> None:
    assert sorted(_model(openapi, "Tick")["properties"]) == TICK_FIELDS


@pytest.mark.parametrize("name", TICK_FIELDS)
def test_every_tick_field_is_checked(openapi: dict[str, Any], name: str) -> None:
    properties = _model(openapi, "Tick")["properties"]
    assert name in properties
    item = _replay_tick()
    item[name] = _wrong(name, properties[name])
    assert _errors(_validator(openapi, "Tick"), item)
    with pytest.raises(FeedContractViolation):
        parse_tick(item, EnvironmentRef("replay", REPLAY_ID), REPLAY_FINGERPRINT)


def test_every_nullable_tick_field_is_read_as_null(openapi: dict[str, Any]) -> None:
    properties = _model(openapi, "Tick")["properties"]
    nullable = sorted(name for name, prop in properties.items() if _nullable(prop))
    assert nullable == ["path_index", "scenario", "session_date"]
    item = _replay_tick()
    for name in nullable:
        item[name] = None
    assert _errors(_validator(openapi, "Tick"), item) == []
    tick = parse_tick(item, EnvironmentRef("replay", REPLAY_ID), REPLAY_FINGERPRINT)
    assert (tick.seq, tick.session, tick.symbol) == (1, 0, item["symbol"])


async def test_an_activated_detail_is_read() -> None:
    feeds = ContractFeeds()
    feed = ReplayFeed(feeds.market_client(), REPLAY_ID)
    assert await feed.activate() == REPLAY_FINGERPRINT
    assert feed.activated_at == datetime.fromisoformat(ACTIVATED_AT).astimezone(UTC)
    assert feed.activated_by == ACTIVATED_BY
    assert feeds.tick_requests() == []  # the frozen value is the detail's


async def test_a_detail_with_null_activation_fields_is_read() -> None:
    feeds = ContractFeeds(detail_fingerprint=False)
    feed = ReplayFeed(feeds.market_client(), REPLAY_ID)
    assert await feed.activate() == REPLAY_FINGERPRINT  # from the first page
    assert (feed.activated_at, feed.activated_by) == (None, None)
    assert len(feeds.tick_requests()) == 1


async def test_a_detail_not_yet_activated_is_refused() -> None:
    feeds = ContractFeeds(detail_fingerprint=False, environment_status="ready")
    with pytest.raises(EnvironmentNotActive) as raised:
        await ReplayFeed(feeds.market_client(), REPLAY_ID).activate()
    assert is_permanent(raised.value)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("activated_at", "2026-11-18T09:30:00"),
        ("activated_at", "yesterday"),
        ("activated_at", 1763458200),
        ("activated_by", 7),
        ("activated_by", ""),
        ("source_fingerprint", ""),
        ("source_fingerprint", 7),
    ],
)
async def test_a_malformed_activation_field_is_refused(name: str, value: object) -> None:
    feeds = ContractFeeds()
    feeds.detail_changes = {name: value}
    with pytest.raises(FeedContractViolation, match=name):
        await ReplayFeed(feeds.market_client(), REPLAY_ID).activate()


async def test_missing_adjusted_prices_is_permanent_and_carries_the_counts() -> None:
    feeds = ContractFeeds()
    feeds.missing = {"AAPL": 3, "KO": 1}
    with pytest.raises(MissingAdjustedPrices) as raised:
        await ReplayFeed(feeds.market_client(), REPLAY_ID).ticks(0, 10)
    assert raised.value.missing == {"AAPL": 3, "KO": 1}
    assert "AAPL (3)" in str(raised.value)
    assert is_permanent(raised.value)
    assert len(feeds.tick_requests()) == 1  # a 4xx is never retried
