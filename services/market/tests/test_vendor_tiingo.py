"""The Tiingo adapter against recorded responses and a mock transport (never the network)."""

import json
import logging
import socket
from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from qs_market import cleaning
from qs_market.vendor.base import (
    UnknownSymbol,
    VendorAuthError,
    VendorProtocolError,
    VendorTransientError,
)
from qs_market.vendor.tiingo import BACKOFF_CAP_SECONDS, MAX_ATTEMPTS, TiingoSource
from tests.conftest import RealVendorCalled

FIXTURES = Path(__file__).parent / "fixtures"
KEY = "sekret-key-0123456789abcdef"
START, END = date(2024, 1, 1), date(2024, 12, 31)

Handler = Callable[[httpx.Request], httpx.Response]


class Harness:
    def __init__(self, handler: Handler) -> None:
        self.requests: list[httpx.Request] = []
        self.sleeps: list[float] = []

        def record(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return handler(request)

        client = httpx.AsyncClient(transport=httpx.MockTransport(record))
        self.source = TiingoSource(
            SecretStr(KEY), client=client, sleep=self._sleep, random=lambda: 0.0
        )

    async def _sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)


def respond(*responses: httpx.Response | Exception) -> Handler:
    """Answers in order; the last answer repeats."""
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, Exception):
            raise item
        return item

    return handler


def fixture_body(symbol: str) -> bytes:
    return (FIXTURES / f"{symbol}.json").read_bytes()


def gate(records: list[dict[str, Any]], start: date, end: date) -> cleaning.GateResult:
    return cleaning.run_gate(
        records,
        calendar="XNYS",
        window_start=start,
        window_end=end,
        as_of=datetime(2025, 1, 1, tzinfo=UTC),
        previous_close=None,
        outlier_log_return=0.25,
    )


async def test_recorded_aapl_maps_and_passes_the_gate() -> None:
    harness = Harness(respond(httpx.Response(200, content=fixture_body("AAPL"))))
    records = await harness.source.fetch_daily("AAPL", START, END)
    assert len(records) == 30
    first = records[0]
    assert first["date"] == "2024-01-02"
    assert first["close"] == Decimal("185.64")
    assert first["adj_close"] == Decimal("183.4133636527")
    assert first["volume"] == Decimal(82488674)
    for record in records:
        assert all(isinstance(v, Decimal) for k, v in record.items() if k != "date")
    assert [r["date"] for r in records if r["dividend"] != 0] == ["2024-02-09"]
    result = gate(records, date(2024, 1, 2), date(2024, 2, 13))
    assert result.rejected == []
    assert len(result.clean) == 30


async def test_recorded_nvda_carries_the_split() -> None:
    harness = Harness(respond(httpx.Response(200, content=fixture_body("NVDA"))))
    records = await harness.source.fetch_daily("NVDA", START, END)
    assert len(records) == 18
    split = next(r for r in records if r["date"] == "2024-06-10")
    assert split["split_factor"] == Decimal("10")
    result = gate(records, date(2024, 5, 28), date(2024, 6, 21))
    assert result.rejected == []
    assert len(result.clean) == 18


async def test_request_shape_and_key_only_in_the_authorization_header() -> None:
    harness = Harness(respond(httpx.Response(200, json=[])))
    await harness.source.fetch_daily("BRK-B", date(2024, 1, 2), date(2024, 1, 5))
    (request,) = harness.requests
    assert request.url.path == "/tiingo/daily/BRK-B/prices"
    assert dict(request.url.params) == {
        "startDate": "2024-01-02",
        "endDate": "2024-01-05",
        "format": "json",
    }
    assert request.headers["Authorization"] == f"Token {KEY}"
    assert KEY not in str(request.url)


async def test_empty_list_is_an_empty_result() -> None:
    harness = Harness(respond(httpx.Response(200, json=[])))
    assert await harness.source.fetch_daily("AAPL", START, END) == []


async def test_missing_fields_are_left_for_the_gate_to_reject() -> None:
    body = [{"date": "2024-01-02T00:00:00.000Z", "close": 10.5}]
    harness = Harness(respond(httpx.Response(200, content=json.dumps(body))))
    (record,) = await harness.source.fetch_daily("AAPL", START, END)
    assert record["open"] is None
    result = gate([record], date(2024, 1, 2), date(2024, 1, 2))
    assert [r.rules for r in result.rejected] == [("malformed",)]


async def test_404_is_unknown_symbol_and_is_not_retried() -> None:
    detail = {"detail": "Error: Ticker 'ZZZZ' not found"}
    harness = Harness(respond(httpx.Response(404, json=detail)))
    with pytest.raises(UnknownSymbol):
        await harness.source.fetch_daily("ZZZZ", START, END)
    assert len(harness.requests) == 1
    assert harness.sleeps == []


@pytest.mark.parametrize("status", [401, 403])
async def test_auth_failures_are_not_retried(status: int) -> None:
    harness = Harness(respond(httpx.Response(status, json={"detail": "bad token"})))
    with pytest.raises(VendorAuthError):
        await harness.source.fetch_daily("AAPL", START, END)
    assert len(harness.requests) == 1


async def test_other_4xx_is_a_protocol_error_and_not_retried() -> None:
    harness = Harness(respond(httpx.Response(400, json={"detail": "bad date"})))
    with pytest.raises(VendorProtocolError):
        await harness.source.fetch_daily("AAPL", START, END)
    assert len(harness.requests) == 1


async def test_429_honours_retry_after_then_succeeds() -> None:
    harness = Harness(
        respond(httpx.Response(429, headers={"Retry-After": "7"}), httpx.Response(200, json=[]))
    )
    assert await harness.source.fetch_daily("AAPL", START, END) == []
    assert harness.sleeps == [7.0]
    assert len(harness.requests) == 2


async def test_500_then_success() -> None:
    harness = Harness(respond(httpx.Response(500), httpx.Response(200, json=[])))
    assert await harness.source.fetch_daily("AAPL", START, END) == []
    assert len(harness.requests) == 2
    assert harness.sleeps == [1.0]


async def test_timeouts_exhaust_after_exactly_four_attempts() -> None:
    harness = Harness(respond(httpx.ReadTimeout("slow")))
    with pytest.raises(VendorTransientError):
        await harness.source.fetch_daily("AAPL", START, END)
    assert len(harness.requests) == MAX_ATTEMPTS == 4
    assert harness.sleeps == [1.0, 2.0, 4.0]


async def test_persistent_429_is_transient() -> None:
    harness = Harness(respond(httpx.Response(429)))
    with pytest.raises(VendorTransientError):
        await harness.source.fetch_daily("AAPL", START, END)
    assert len(harness.requests) == 4


async def test_backoff_grows_and_is_capped() -> None:
    harness = Harness(respond(httpx.Response(200, json=[])))
    delays = [harness.source._delay(n) for n in range(1, 10)]
    assert delays[:4] == [1.0, 2.0, 4.0, 8.0]
    assert delays == sorted(delays)
    assert max(delays) == BACKOFF_CAP_SECONDS


async def test_jitter_only_shortens_the_delay() -> None:
    source = TiingoSource(SecretStr(KEY), random=lambda: 1.0)
    assert source._delay(3) == pytest.approx(4.0 * 0.75)
    await source.aclose()


async def test_malformed_json_is_a_protocol_error() -> None:
    harness = Harness(respond(httpx.Response(200, content=b"<html>oops")))
    with pytest.raises(VendorProtocolError):
        await harness.source.fetch_daily("AAPL", START, END)
    assert len(harness.requests) == 1


@pytest.mark.parametrize("body", [{"detail": "nope"}, [1, 2], "text"])
async def test_wrong_shape_is_a_protocol_error(body: Any) -> None:
    harness = Harness(respond(httpx.Response(200, json=body)))
    with pytest.raises(VendorProtocolError):
        await harness.source.fetch_daily("AAPL", START, END)


async def test_the_key_never_leaks(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    cases = [
        respond(httpx.Response(401, text=f"bad token {KEY}")),
        respond(httpx.Response(404)),
        respond(httpx.Response(500)),
        respond(httpx.ConnectTimeout("t")),
        respond(httpx.Response(200, content=b"{")),
    ]
    raised = 0
    for handler in cases:
        harness = Harness(handler)
        try:
            await harness.source.fetch_daily("AAPL", START, END)
        except Exception as exc:
            raised += 1
            assert KEY not in str(exc)
            assert KEY not in repr(exc)
            assert KEY not in repr(exc.__cause__)
        assert KEY not in repr(harness.source)
    assert raised == len(cases)
    assert KEY not in caplog.text
    assert caplog.text  # the retries were logged, and still without the key


async def test_real_host_guard_trips_on_resolution() -> None:
    with pytest.raises(RealVendorCalled):
        socket.getaddrinfo("api.tiingo.com", 443)
    with pytest.raises(RealVendorCalled):
        socket.create_connection(("api.tiingo.com", 443))
