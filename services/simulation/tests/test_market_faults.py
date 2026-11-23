"""Faults on the way to the market, through the real service client (B-NFR-10, tracker I-26): a
timeout or a 503 is retried, a service that keeps failing opens the breaker so calls are not sent,
the breaker lets one trial through after its reset time, a 404 is not a fault, and the correlation
request carries the same idempotency key on every try. Nothing here needs a database."""

import json
import uuid
from collections.abc import Callable
from datetime import date

import httpx
import pytest
from pydantic import SecretStr

from qs_simulation.adapters.correlation_sources import MarketCorrelationSource
from qs_simulation.adapters.market_client import JsonPoster
from qs_simulation.adapters.price_sources import MarketPriceSource
from qs_simulation.ports import InstrumentNotFound, PriceSourceError
from qs_template.service_client import CircuitBreaker, ServiceClient, StaticServiceToken

INSTRUMENT = uuid.uuid4()
OTHER = uuid.uuid4()
BARS = {
    "items": [{"session_date": "2020-01-02", "adj_close": "75.0875", "revision": 1}],
    "next_cursor": None,
}


class Clock:
    """A clock the test moves, so the breaker's reset time costs no waiting."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class Market:
    """A market that answers from a script and counts what reached it."""

    def __init__(self, script: Callable[[int, httpx.Request], httpx.Response]) -> None:
        self.script = script
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.script(len(self.requests), request)


def client(
    market: Market, *, retries: int = 2, threshold: int = 5, clock: Clock | None = None
) -> ServiceClient:
    slept: list[float] = []

    async def no_sleep(seconds: float) -> None:
        slept.append(seconds)

    return ServiceClient(
        "http://market:8000",
        caller="simulation",
        tokens=StaticServiceToken(SecretStr("s" * 40), environment="local"),
        transport=httpx.MockTransport(market),
        retries=retries,
        sleep=no_sleep,
        breaker=CircuitBreaker(
            failure_threshold=threshold, reset_after_seconds=30.0, clock=clock or Clock()
        ),
    )


def bars_ok(_: int, request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json=BARS)


async def window(source: MarketPriceSource) -> list[object]:
    return list(await source.window(INSTRUMENT, date(2020, 1, 1), date(2020, 12, 31)))


async def test_a_timeout_is_retried_and_the_window_still_arrives() -> None:
    def script(n: int, request: httpx.Request) -> httpx.Response:
        if n == 1:
            raise httpx.ReadTimeout("slow", request=request)
        return httpx.Response(200, json=BARS)

    market = Market(script)
    points = await window(MarketPriceSource(client(market)))
    assert len(points) == 1 and len(market.requests) == 2
    assert all(r.headers["Authorization"] == f"Bearer {'s' * 40}" for r in market.requests)


@pytest.mark.parametrize("status", [429, 502, 503, 504])
async def test_a_busy_or_down_answer_is_retried(status: int) -> None:
    market = Market(lambda n, r: httpx.Response(status if n < 3 else 200, json=BARS))
    assert len(await window(MarketPriceSource(client(market)))) == 1
    assert len(market.requests) == 3


async def test_a_market_that_never_answers_ends_as_a_price_source_error_the_job_retries() -> None:
    def script(n: int, request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    market = Market(script)
    with pytest.raises(PriceSourceError, match="market service"):
        await window(MarketPriceSource(client(market)))
    assert len(market.requests) == 3  # the first try and two retries, then it gives up


async def test_a_market_that_keeps_failing_opens_the_breaker_and_calls_stop_being_sent() -> None:
    market = Market(lambda n, r: httpx.Response(500, json={"title": "broken"}))
    source = MarketPriceSource(client(market, retries=0, threshold=3))
    for _ in range(3):
        with pytest.raises(PriceSourceError):
            await window(source)
    assert len(market.requests) == 3
    with pytest.raises(PriceSourceError, match="failed too often"):
        await window(source)  # refused at once: the market is not asked
    assert len(market.requests) == 3


async def test_after_its_reset_time_the_breaker_lets_one_trial_through_and_closes_on_success() -> (
    None
):
    clock = Clock()
    healthy = {"yes": False}

    def script(n: int, request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=BARS) if healthy["yes"] else httpx.Response(500, json={})

    market = Market(script)
    source = MarketPriceSource(client(market, retries=0, threshold=2, clock=clock))
    for _ in range(2):
        with pytest.raises(PriceSourceError):
            await window(source)
    with pytest.raises(PriceSourceError, match="failed too often"):
        await window(source)
    assert len(market.requests) == 2
    clock.now = 31.0  # past the reset time, and the market has recovered
    healthy["yes"] = True
    assert len(await window(source)) == 1  # the trial call
    assert len(await window(source)) == 1  # and the circuit is closed again
    assert len(market.requests) == 4


async def test_a_trial_that_fails_opens_the_breaker_again() -> None:
    clock = Clock()
    market = Market(lambda n, r: httpx.Response(500, json={}))
    source = MarketPriceSource(client(market, retries=0, threshold=2, clock=clock))
    for _ in range(2):
        with pytest.raises(PriceSourceError):
            await window(source)
    clock.now = 31.0
    with pytest.raises(PriceSourceError):
        await window(source)  # the one trial, which fails
    assert len(market.requests) == 3
    with pytest.raises(PriceSourceError, match="failed too often"):
        await window(source)
    assert len(market.requests) == 3


async def test_an_unknown_instrument_is_not_a_fault_and_never_opens_the_breaker() -> None:
    market = Market(lambda n, r: httpx.Response(404, json={"title": "not found"}))
    source = MarketPriceSource(client(market, retries=0, threshold=2))
    for _ in range(6):
        with pytest.raises(InstrumentNotFound):
            await window(source)
    assert len(market.requests) == 6  # every one was sent: the market answered each time


async def test_the_correlation_request_is_retried_with_the_same_idempotency_key() -> None:
    answer = {
        "windows": [
            {
                "start": "2020-01-01",
                "end": "2020-12-31",
                "symbols": ["AAPL", "KO"],
                "matrix": [["1", "0.4"], ["0.4", "1"]],
                "n_obs": 250,
            }
        ]
    }

    def script(n: int, request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            symbol = "AAPL" if request.url.path.endswith(str(INSTRUMENT)) else "KO"
            return httpx.Response(200, json={"symbol": symbol, "name": symbol})
        if len([r for r in market.requests if r.method == "POST"]) == 1:
            return httpx.Response(503, json={})
        return httpx.Response(200, json=answer)

    market = Market(script)
    served = client(market)
    prices = MarketPriceSource(served)
    matrix = await MarketCorrelationSource(JsonPoster(served), prices).matrix(
        [INSTRUMENT, OTHER], date(2020, 1, 1), date(2020, 12, 31)
    )
    assert matrix.values[0][1] == pytest.approx(0.4)
    posts = [r for r in market.requests if r.method == "POST"]
    assert len(posts) == 2  # one failure, one retry
    assert posts[0].headers["Idempotency-Key"] == posts[1].headers["Idempotency-Key"]
    assert json.loads(posts[0].content) == json.loads(posts[1].content)
