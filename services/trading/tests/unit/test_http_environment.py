"""The HTTP market adapters (A17) on hand-made answers: status mapping (permanent or
transient), the page checks, the page-size cap, the fingerprint cache, the client over K3's
``ServiceClient`` (token header, retries, circuit breaker, the mapping of
``ServiceCallError``), and the worker's environment factory."""

import uuid
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from qs_template.service_client import CircuitBreaker, StaticServiceToken
from qs_trading.adapters.feed_client import (
    FeedResponse,
    FeedUnavailable,
    ServiceClientFeed,
    service_client_feed,
)
from qs_trading.adapters.http_environment import (
    EnvironmentNotActive,
    EnvironmentNotFound,
    FeedContractViolation,
    FeedNotImplemented,
    FeedRefused,
    FeedUnauthorized,
    ReplayFeed,
    SimulationPathFeed,
)
from qs_trading.jobs import (
    PERMANENT_ERRORS,
    environment_factory,
    is_permanent,
    no_environments,
    service_tokens,
)
from qs_trading.ports.market_environment import (
    MAX_PAGE_SIZE,
    EnvironmentRef,
    FingerprintChanged,
    MarketEnvironmentError,
    MissingAdjustedPrices,
)
from qs_trading.settings import TradingSettings

ENV = "6f1c2a4e-3b8d-4f7a-9c21-0a5e7d9b1c01"
RUN = "a4d3c2b1-7e6f-4a5b-8c9d-0e1f2a3b4c5d"
FP = "xxh3:3f9a1c0e5b7d2a48c6e10f93b5d7a2c1"
TOKEN = "unit-service-token-0123456789abcdef0123"
SYMBOLS = ("AAPL", "KO", "MSFT")


def _tick(seq: int, **changes: Any) -> dict[str, Any]:
    session, index = divmod(seq - 1, len(SYMBOLS))
    tick = {
        "env_id": ENV,
        "env_type": "replay",
        "source_fingerprint": FP,
        "seq": seq,
        "session": session,
        "session_date": f"2020-01-{session + 2:02d}",
        "ts": f"2020-01-{session + 2:02d}T21:00:00Z",
        "instrument_id": str(uuid.UUID(int=index + 1)),
        "symbol": SYMBOLS[index],
        "open": "10.0000000000",
        "high": "11.0000000000",
        "low": "9.0000000000",
        "close": "10.5000000000",
        "volume": "1000.00000000",
        "path_index": None,
        "scenario": None,
    }
    tick.update(changes)
    return tick


class Script:
    """A FeedClient answering from a function, recording what was asked."""

    def __init__(self, answer: Callable[[str, dict[str, Any]], FeedResponse]) -> None:
        self.answer = answer
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def get(self, path: str, params: Any = None) -> FeedResponse:
        self.calls.append((path, dict(params or {})))
        return self.answer(path, dict(params or {}))


def _feed_of(total: int, fingerprint: str = FP, status: str = "active") -> Script:
    """A well-behaved replay feed of ``total`` ticks."""

    def answer(path: str, params: dict[str, Any]) -> FeedResponse:
        if not path.endswith("/ticks"):
            return FeedResponse(200, {}, {"id": ENV, "type": "historical_replay", "status": status})
        after, limit = int(params["after_seq"]), int(params["limit"])
        seqs = range(after + 1, min(after + limit, total) + 1)
        items = [_tick(s, source_fingerprint=fingerprint) for s in seqs]
        more = after + limit < total
        body = {"items": items, "next_after_seq": items[-1]["seq"] if items and more else None}
        return FeedResponse(200, {"x-source-fingerprint": fingerprint}, body)

    return Script(answer)


def _page(
    items: list[dict[str, Any]],
    next_after_seq: int | None = None,
    headers: dict[str, str] | None = None,
) -> Script:
    body = {"items": items, "next_after_seq": next_after_seq}
    hdrs = {"x-source-fingerprint": FP} if headers is None else headers
    return Script(lambda path, params: FeedResponse(200, hdrs, body))


def _status(status: int, kind: str = "", detail: str = "no") -> Script:
    body = (
        {"type": f"urn:quantsim:problem:{kind}", "title": kind, "status": status, "detail": detail}
        if kind
        else None
    )
    return Script(lambda path, params: FeedResponse(status, {}, body))


# --- status mapping -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "kind", "error", "permanent"),
    [
        (401, "unauthorized", FeedUnauthorized, True),
        (403, "forbidden", FeedUnauthorized, True),
        (404, "not-found", EnvironmentNotFound, True),
        (409, "environment-not-active", EnvironmentNotActive, True),
        (422, "missing-adjusted-prices", MissingAdjustedPrices, True),
        (422, "missing_adjusted_prices", MissingAdjustedPrices, True),
        (422, "not-a-replay-environment", FeedRefused, True),
        (422, "unsupported-frequency", FeedRefused, True),
        (400, "", FeedRefused, True),
        (501, "not-implemented", FeedNotImplemented, True),
        (429, "", FeedUnavailable, False),
        (500, "", FeedUnavailable, False),
        (502, "", FeedUnavailable, False),
        (503, "upstream-down", FeedUnavailable, False),
        (504, "", FeedUnavailable, False),
    ],
)
async def test_every_status_maps_to_a_permanent_or_transient_error(
    status: int, kind: str, error: type[Exception], permanent: bool
) -> None:
    feed = ReplayFeed(_status(status, kind), ENV)
    for read in (feed.activate(), feed.ticks(0, 10)):
        with pytest.raises(error) as raised:
            await read
        assert is_permanent(raised.value) is permanent
        assert isinstance(raised.value, MarketEnvironmentError)


async def test_a_refused_token_names_the_setting_and_never_the_token() -> None:
    with pytest.raises(FeedUnauthorized, match="QS_SERVICE_TOKEN") as raised:
        await ReplayFeed(_status(401, "unauthorized"), ENV).activate()
    assert TOKEN not in str(raised.value)


def test_the_transient_error_is_not_permanent_and_the_feed_errors_are() -> None:
    assert not issubclass(FeedUnavailable, PERMANENT_ERRORS)
    for error in (
        FeedUnauthorized,
        EnvironmentNotFound,
        EnvironmentNotActive,
        FeedRefused,
        FeedNotImplemented,
        FeedContractViolation,
        MissingAdjustedPrices,
        FingerprintChanged,
    ):
        assert issubclass(error, PERMANENT_ERRORS), error


# --- the page checks ------------------------------------------------------------------------


async def test_pages_follow_next_after_seq() -> None:
    feed = ReplayFeed(_feed_of(7), ENV)
    first = await feed.ticks(0, 3)
    assert [t.seq for t in first.items] == [1, 2, 3] and first.next_after_seq == 3
    assert first.fingerprint == FP
    last = await feed.ticks(6, 3)
    assert [t.seq for t in last.items] == [7] and last.next_after_seq is None
    assert (await feed.ticks(7, 3)).items == []


async def test_a_tick_is_mapped_to_the_port() -> None:
    tick = (await ReplayFeed(_feed_of(1), ENV).ticks(0, 1)).items[0]
    assert (tick.seq, tick.session, tick.symbol) == (1, 0, "AAPL")
    assert tick.ts.isoformat() == "2020-01-02T21:00:00+00:00"
    assert str(tick.close) == "10.5000000000"


@pytest.mark.parametrize("limit", [0, MAX_PAGE_SIZE + 1, 5000])
async def test_a_page_above_2000_is_never_asked_for(limit: int) -> None:
    client = _feed_of(10)
    with pytest.raises(ValueError, match="2000"):
        await ReplayFeed(client, ENV).ticks(0, limit)
    assert client.calls == []


async def test_the_largest_page_is_asked_for_as_2000() -> None:
    client = _feed_of(10)
    await ReplayFeed(client, ENV).ticks(0, MAX_PAGE_SIZE)
    assert client.calls[0][1] == {"after_seq": 0, "limit": 2000}


@pytest.mark.parametrize(
    ("items", "next_after_seq", "message"),
    [
        ([_tick(1), _tick(3)], None, "without gaps"),
        ([_tick(2), _tick(3)], None, "expected 1, got 2"),
        ([_tick(2), _tick(1)], None, "without gaps"),
        ([_tick(1), _tick(2, symbol="AAPL")], None, "ordered"),
        ([_tick(1), _tick(2)], 1, "not the last seq"),
        ([], 4, "not the last seq"),
        ([_tick(1, close=10.5)], None, "decimal string"),
        ([_tick(1, close="1e1")], None, "decimal string"),
        ([_tick(1, low="12.0")], None, "high is below low"),
        ([_tick(1, open="0")], None, "above zero"),
        ([_tick(1, ts="2020-01-02T21:00:00")], None, "zone"),
        ([_tick(1, env_id=RUN)], None, "belongs to"),
        ([_tick(1, env_type="synthetic")], None, "not a replay tick"),
        ([_tick(1, path_index=0)], None, "carries path_index"),
        ([_tick(1, source_fingerprint="xxh3:other")], None, "carries source_fingerprint"),
        ([{**_tick(1), "seq": True}], None, "whole number"),
    ],
)
async def test_a_page_that_breaks_the_contract_is_refused(
    items: list[dict[str, Any]], next_after_seq: int | None, message: str
) -> None:
    feed = ReplayFeed(_page(items, next_after_seq), ENV)
    with pytest.raises(FeedContractViolation, match=message) as raised:
        await feed.ticks(0, 10)
    assert is_permanent(raised.value)


async def test_a_page_larger_than_asked_is_refused() -> None:
    with pytest.raises(FeedContractViolation, match="asked for 1"):
        await ReplayFeed(_page([_tick(1), _tick(2)]), ENV).ticks(0, 1)


async def test_the_order_is_checked_across_pages() -> None:
    pages = {0: [_tick(1), _tick(2)], 2: [_tick(3, session=0, symbol="AAPL")]}

    def answer(path: str, params: dict[str, Any]) -> FeedResponse:
        after = int(params["after_seq"])
        return FeedResponse(
            200,
            {"x-source-fingerprint": FP},
            {"items": pages[after], "next_after_seq": 2 if after == 0 else None},
        )

    feed = ReplayFeed(Script(answer), ENV)
    await feed.ticks(0, 2)
    with pytest.raises(FeedContractViolation, match="ordered"):
        await feed.ticks(2, 2)


async def test_unknown_fields_and_a_null_session_date_are_ignored() -> None:
    page = _page([_tick(1, share_class="A", session_date=None)])
    assert len((await ReplayFeed(page, ENV).ticks(0, 10)).items) == 1


async def test_without_the_header_the_ticks_fingerprint_is_used() -> None:
    assert (await ReplayFeed(_page([_tick(1)], headers={}), ENV).ticks(0, 1)).fingerprint == FP
    empty = ReplayFeed(_page([], headers={}), ENV)
    with pytest.raises(FeedContractViolation, match="X-Source-Fingerprint"):
        await empty.ticks(0, 1)


async def test_a_body_that_is_not_a_page_is_refused() -> None:
    feed = ReplayFeed(Script(lambda p, q: FeedResponse(200, {}, ["not", "a", "page"])), ENV)
    with pytest.raises(FeedContractViolation, match="items, next_after_seq"):
        await feed.ticks(0, 1)


# --- activation and the fingerprint cache ---------------------------------------------------


async def test_a_page_under_another_fingerprint_after_activation_is_fingerprint_changed() -> None:
    client = _feed_of(5)
    feed = ReplayFeed(client, ENV)
    assert await feed.activate() == FP
    client.answer = _feed_of(5, fingerprint="xxh3:new").answer
    with pytest.raises(FingerprintChanged) as raised:
        await feed.ticks(0, 5)
    assert (raised.value.expected, raised.value.actual) == (FP, "xxh3:new")
    assert feed.frozen_fingerprint == FP


async def test_the_fingerprint_is_cached_for_the_interval() -> None:
    now = [100.0]
    client = _feed_of(5)
    feed = ReplayFeed(client, ENV, fingerprint_ttl_seconds=30, clock=lambda: now[0])
    await feed.activate()  # the detail has no fingerprint: one probe
    calls = len(client.calls)
    for _ in range(50):
        assert await feed.fingerprint() == FP
    assert len(client.calls) == calls
    now[0] += 30
    assert await feed.fingerprint() == FP
    assert len(client.calls) == calls + 1
    assert client.calls[-1][1] == {"after_seq": 0, "limit": 1}


async def test_a_page_with_another_fingerprint_replaces_the_cached_one() -> None:
    client = _feed_of(5)
    feed = ReplayFeed(client, ENV, fingerprint_ttl_seconds=3600)
    await feed.activate()
    client.answer = _feed_of(5, fingerprint="xxh3:new").answer
    with pytest.raises(FingerprintChanged):
        await feed.ticks(0, 5)
    assert await feed.fingerprint() == "xxh3:new"


async def test_a_zero_interval_asks_every_time() -> None:
    client = _feed_of(5)
    feed = ReplayFeed(client, ENV, fingerprint_ttl_seconds=0)
    await feed.fingerprint()
    await feed.fingerprint()
    assert len(client.calls) == 2


async def test_a_synthetic_environment_detail_is_refused_by_the_replay_feed() -> None:
    client = Script(lambda p, q: FeedResponse(200, {}, {"id": ENV, "type": "synthetic"}))
    with pytest.raises(FeedRefused, match="not a historical replay"):
        await ReplayFeed(client, ENV).activate()


async def test_the_simulation_feed_always_sends_the_path() -> None:
    def answer(path: str, params: dict[str, Any]) -> FeedResponse:
        if not path.endswith("/ticks"):
            return FeedResponse(200, {}, {"id": RUN, "status": "completed", "n_paths": 9})
        item = _tick(1, env_id=RUN, env_type="synthetic", path_index=4, session_date=None)
        return FeedResponse(
            200, {"x-source-fingerprint": FP}, {"items": [item], "next_after_seq": None}
        )

    client = Script(answer)
    feed = SimulationPathFeed(client, RUN, 4)
    assert await feed.activate() == FP
    assert client.calls == [
        (f"/api/simulation/runs/{RUN}", {}),
        (f"/api/simulation/runs/{RUN}/ticks", {"path": 4, "after_seq": 0, "limit": 1}),
    ]


def test_a_simulation_feed_needs_a_path_index() -> None:
    with pytest.raises(ValueError, match="path_index"):
        SimulationPathFeed(_feed_of(1), RUN, -1)


async def test_a_tick_on_another_path_is_refused() -> None:
    item = _tick(1, env_id=RUN, env_type="synthetic", path_index=1)
    with pytest.raises(FeedContractViolation, match="on path 1, not 0"):
        await SimulationPathFeed(_page([item]), RUN, 0).ticks(0, 1)


# --- the client over K3's ServiceClient -----------------------------------------------------


async def _no_wait(seconds: float) -> None:
    return None


def _client(
    handler: Callable[[httpx.Request], httpx.Response], **options: Any
) -> ServiceClientFeed:
    tokens = StaticServiceToken(SecretStr(TOKEN), environment="dev")
    return service_client_feed(
        "http://market.test/",
        tokens,
        transport=httpx.MockTransport(handler),
        sleep=_no_wait,
        **options,
    )


async def test_the_client_sends_the_bearer_token_and_returns_the_page() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={"items": [], "next_after_seq": None},
            headers={"X-Source-Fingerprint": FP},
        )

    client = _client(handler)
    response = await client.get("/api/market/environments/x/ticks", {"after_seq": 0})
    await client.aclose()
    assert response.status == 200
    assert response.header("X-Source-Fingerprint") == FP
    assert response.body == {"items": [], "next_after_seq": None}
    request = seen[0]
    assert request.headers["Authorization"] == f"Bearer {TOKEN}"
    assert request.headers["X-Calling-Service"] == "trading"
    assert str(request.url) == "http://market.test/api/market/environments/x/ticks?after_seq=0"


@pytest.mark.parametrize(
    ("status", "kind", "error"),
    [
        (401, "unauthorized", FeedUnauthorized),
        (404, "not-found", EnvironmentNotFound),
        (409, "environment-not-active", EnvironmentNotActive),
        (422, "missing-adjusted-prices", MissingAdjustedPrices),
        (422, "unsupported-frequency", FeedRefused),
        (501, "not-implemented", FeedNotImplemented),
    ],
)
async def test_an_upstream_error_keeps_the_providers_status_and_is_not_retried(
    status: int, kind: str, error: type[Exception]
) -> None:
    """K3's upstream-error (502) carries the provider's 4xx or 501 and its problem body:
    the adapter maps that status, and the job fails without a retry."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        body = {"type": f"urn:quantsim:problem:{kind}", "title": kind, "status": status}
        return httpx.Response(status, json={**body, "detail": "no", "missing": {"AAPL": 2}})

    with pytest.raises(error) as raised:
        await ReplayFeed(_client(handler), ENV).ticks(0, 10)
    assert is_permanent(raised.value)
    assert len(seen) == 1
    if isinstance(raised.value, MissingAdjustedPrices):
        assert raised.value.missing == {"AAPL": 2}


async def test_a_500_is_transient_and_not_retried_by_the_client() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(500, text="<html>oops")

    with pytest.raises(FeedUnavailable) as raised:
        await ReplayFeed(_client(handler), ENV).ticks(0, 1)
    assert not is_permanent(raised.value)
    assert len(seen) == 1


@pytest.mark.parametrize("status", [429, 502, 503, 504])
async def test_a_busy_provider_is_retried_then_transient(status: int) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status)

    with pytest.raises(FeedUnavailable, match="did not answer") as raised:
        await ReplayFeed(_client(handler, retries=2), ENV).ticks(0, 1)
    assert not is_permanent(raised.value)
    assert len(seen) == 3


async def test_a_retry_that_succeeds_reads_the_page() -> None:
    answers = iter([httpx.Response(503), httpx.Response(503)])

    def handler(request: httpx.Request) -> httpx.Response:
        body = {"items": [_tick(1)], "next_after_seq": None}
        return next(answers, httpx.Response(200, json=body, headers={"X-Source-Fingerprint": FP}))

    page = await ReplayFeed(_client(handler), ENV).ticks(0, 1)
    assert [t.seq for t in page.items] == [1]


@pytest.mark.parametrize(
    "error", [httpx.ConnectError("refused"), httpx.ReadTimeout("slow"), httpx.ConnectTimeout("x")]
)
async def test_connection_errors_and_timeouts_are_transient(error: Exception) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise error

    with pytest.raises(FeedUnavailable) as raised:
        await ReplayFeed(_client(handler, retries=1), ENV).ticks(0, 1)
    assert not is_permanent(raised.value)


async def test_an_open_circuit_is_transient_and_sends_nothing() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(503)

    breaker = CircuitBreaker(failure_threshold=2, reset_after_seconds=60)
    feed = ReplayFeed(_client(handler, retries=1, breaker=breaker), ENV)
    with pytest.raises(FeedUnavailable, match="did not answer"):
        await feed.ticks(0, 1)
    assert breaker.state == "open"
    sent = len(seen)
    with pytest.raises(FeedUnavailable, match="failed too often") as raised:
        await feed.ticks(0, 1)
    assert not is_permanent(raised.value)
    assert len(seen) == sent


async def test_the_token_is_never_in_an_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"type": "urn:quantsim:problem:unauthorized"})

    with pytest.raises(FeedUnauthorized) as raised:
        await ReplayFeed(_client(handler), ENV).activate()
    assert TOKEN not in str(raised.value)
    assert TOKEN not in repr(raised.value)


# --- settings and the factory ---------------------------------------------------------------


def _settings(environment: str = "dev", **values: Any) -> TradingSettings:
    return TradingSettings(
        environment=environment,
        database_url=SecretStr("postgresql+asyncpg://unused:unused@127.0.0.1:1/unused"),
        redis_url=SecretStr("redis://127.0.0.1:1/0"),
        **values,
    )


def test_without_feed_urls_the_factory_is_unchanged() -> None:
    assert environment_factory(_settings()) is no_environments


def test_the_feed_urls_pick_the_http_adapters() -> None:
    settings = _settings(
        trading_market_url="http://market:8000",
        trading_simulation_url="http://simulation:8000",
        service_token=SecretStr(TOKEN),
        trading_fingerprint_cache_seconds=5,
    )
    open_environment = environment_factory(settings)
    replay = open_environment(EnvironmentRef("replay", ENV))
    path = open_environment(EnvironmentRef("simulation", RUN, 3))
    assert isinstance(replay, ReplayFeed) and replay.ref == EnvironmentRef("replay", ENV)
    assert isinstance(path, SimulationPathFeed)
    assert path.ref == EnvironmentRef("simulation", RUN, 3)


def test_a_kind_without_a_url_falls_back_to_the_demo_or_none() -> None:
    settings = _settings(trading_market_url="http://market:8000", service_token=SecretStr(TOKEN))
    open_environment = environment_factory(settings)
    assert isinstance(open_environment(EnvironmentRef("replay", ENV)), ReplayFeed)
    with pytest.raises(MarketEnvironmentError, match="no market adapter"):
        open_environment(EnvironmentRef("simulation", RUN, 0))


def test_a_feed_url_needs_the_service_token() -> None:
    with pytest.raises(ValueError, match="QS_SERVICE_TOKEN"):
        environment_factory(_settings(trading_simulation_url="http://simulation:8000"))


def test_the_factory_reads_through_the_service_client_with_the_given_tokens() -> None:
    class Tokens:
        async def token(self) -> str:
            return TOKEN

    settings = _settings(trading_market_url="http://market:8000")
    open_environment = environment_factory(settings, tokens=Tokens())
    replay = open_environment(EnvironmentRef("replay", ENV))
    assert isinstance(replay, ReplayFeed)
    assert isinstance(replay._client, ServiceClientFeed)


async def test_the_default_tokens_are_the_static_dev_token() -> None:
    tokens = service_tokens(_settings(service_token=SecretStr(TOKEN)))
    assert isinstance(tokens, StaticServiceToken)
    assert await tokens.token() == TOKEN


def test_injected_clients_need_no_url() -> None:
    open_environment = environment_factory(_settings(), market=_feed_of(1))
    assert isinstance(open_environment(EnvironmentRef("replay", ENV)), ReplayFeed)


@pytest.mark.parametrize("environment", ["test", "acc", "prod"])
def test_the_service_token_is_refused_outside_local_and_dev(environment: str) -> None:
    with pytest.raises(ValidationError, match="QS_SERVICE_TOKEN"):
        _settings(environment, service_token=SecretStr(TOKEN))


def test_the_settings_are_read_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QS_DATABASE_URL", "postgresql+asyncpg://u:p@127.0.0.1:1/d")
    monkeypatch.setenv("QS_REDIS_URL", "redis://127.0.0.1:1/0")
    monkeypatch.setenv("QS_TRADING_MARKET_URL", "http://market:8000")
    monkeypatch.setenv("QS_TRADING_SIMULATION_URL", "http://simulation:8000")
    monkeypatch.setenv("QS_SERVICE_TOKEN", TOKEN)
    settings = TradingSettings()
    assert settings.trading_market_url == "http://market:8000"
    assert settings.trading_simulation_url == "http://simulation:8000"
    assert settings.service_token is not None
    assert TOKEN not in repr(settings)
