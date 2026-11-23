"""The market sources come from the service client when a market URL is configured (K3, I-02):
the token and the idempotency key on the wire, the answers the adapters read, and the 503 path when
nothing is configured."""

import json
import uuid
from datetime import date

import httpx
from pydantic import SecretStr

from qs_simulation.adapters.market_client import idempotency_key
from qs_simulation.composition import default_dependencies, market_sources
from qs_simulation.settings import SimulationSettings

TOKEN = "s" * 40
INSTRUMENT = uuid.uuid4()
OTHER = uuid.uuid4()


def settings(**extra: object) -> SimulationSettings:
    return SimulationSettings(
        database_url=SecretStr("postgresql+asyncpg://unused"),
        redis_url=SecretStr("redis://unused"),
        auth_jwks_url="http://127.0.0.1:1/jwks.json",
        content_hash="test-hash",
        environment="local",
        service_token=SecretStr(TOKEN),
        **extra,  # type: ignore[arg-type]
    )


def test_without_a_market_url_there_are_no_sources() -> None:
    deps = default_dependencies(settings())
    assert deps.price_source is None and deps.correlation_source is None
    assert not deps.can_calibrate and not deps.can_run


def test_with_a_market_url_both_sources_exist() -> None:
    deps = default_dependencies(settings(simulation_market_url="http://market:8000"))
    assert deps.can_calibrate and deps.can_run


async def test_the_sources_read_the_market_with_the_service_token() -> None:
    seen: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        path = request.url.path
        if path == f"/api/market/instruments/{INSTRUMENT}":
            return httpx.Response(200, json={"symbol": "AAPL", "name": "Apple Inc."})
        if path == f"/api/market/instruments/{OTHER}":
            return httpx.Response(200, json={"symbol": "KO", "name": "Coca-Cola"})
        if path == f"/api/market/instruments/{INSTRUMENT}/bars":
            bar = {"session_date": "2020-01-02", "adj_close": "75.0875", "revision": 1}
            return httpx.Response(200, json={"items": [bar], "next_cursor": None})
        if path == "/api/market/correlations":
            window = {
                "start": "2020-01-01",
                "end": "2020-12-31",
                "symbols": ["AAPL", "KO"],
                "matrix": [["1", "0.4"], ["0.4", "1"]],
                "n_obs": 250,
            }
            return httpx.Response(200, json={"windows": [window]})
        return httpx.Response(404, json={"title": "not found"})

    prices, correlations = market_sources(
        settings(simulation_market_url="http://market:8000"),
        transport=httpx.MockTransport(answer),
    )
    points = await prices.window(INSTRUMENT, date(2020, 1, 1), date(2020, 12, 31))
    assert [str(p.adj_close) for p in points] == ["75.0875"]
    await correlations.matrix([INSTRUMENT, OTHER], date(2020, 1, 1), date(2020, 12, 31))
    assert seen and all(r.headers["Authorization"] == f"Bearer {TOKEN}" for r in seen)
    post = next(r for r in seen if r.method == "POST")
    assert post.headers["Idempotency-Key"] == idempotency_key(
        "/api/market/correlations", json.loads(post.content)
    )
    assert not any("Idempotency-Key" in r.headers for r in seen if r.method == "GET")


def test_the_same_body_gets_the_same_key_and_another_body_another() -> None:
    body = {"b": 1, "a": [1, 2]}
    assert idempotency_key("/x", body) == idempotency_key("/x", {"a": [1, 2], "b": 1})
    assert idempotency_key("/x", body) != idempotency_key("/x", {"a": [1, 3], "b": 1})
    assert idempotency_key("/x", body) != idempotency_key("/y", body)


def test_a_market_url_without_usable_credentials_degrades_instead_of_crashing() -> None:
    bare = SimulationSettings(
        database_url=SecretStr("postgresql+asyncpg://unused"),
        redis_url=SecretStr("redis://unused"),
        auth_jwks_url="http://127.0.0.1:1/jwks.json",
        content_hash="test-hash",
        environment="local",
        simulation_market_url="http://market:8000",
    )  # no service token and no client secret
    deps = default_dependencies(bare)
    assert deps.price_source is None and deps.correlation_source is None
    assert (
        not deps.can_calibrate and not deps.can_run
    )  # the routes answer 503; the service stays up
