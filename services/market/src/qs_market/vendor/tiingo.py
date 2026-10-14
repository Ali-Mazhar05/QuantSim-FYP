"""Tiingo end-of-day prices (ingestion plan section 2.2).

What the vendor really does, verified live: raw prices are not split-adjusted and the
adjusted ones are restated backwards at every dividend or split; the date is midnight UTC
rather than the session close; it sends no rate-limit headers, so the request budget is
counted by us (``budget.py``); and a call takes one to eleven seconds.

Money is Decimal end to end: the body is parsed with ``parse_float=Decimal`` so no binary
float is ever involved (NFR-INT-001). The API key is a SecretStr, sent only in the
Authorization header and never part of a log line, a message or a repr.
"""

import asyncio
import json
import logging
import random as random_module
from collections.abc import Awaitable, Callable
from datetime import date
from decimal import Decimal
from typing import Any
from urllib.parse import quote

import httpx
from pydantic import SecretStr

from qs_market.vendor.base import (
    UnknownSymbol,
    VendorAuthError,
    VendorProtocolError,
    VendorTransientError,
)
from qs_market.vendor.budget import RequestBudget

log = logging.getLogger("qs_market.vendor.tiingo")

MAX_ATTEMPTS = 4
BACKOFF_BASE_SECONDS = 1.0
BACKOFF_CAP_SECONDS = 30.0
JITTER_FRACTION = 0.25  # each delay is shortened by up to this fraction, never lengthened
RETRY_AFTER_CAP_SECONDS = 120.0

# Tiingo field -> the cleaning gate's key
FIELD_MAP = {
    "date": "date",
    "open": "open",
    "high": "high",
    "low": "low",
    "close": "close",
    "volume": "volume",
    "adjOpen": "adj_open",
    "adjHigh": "adj_high",
    "adjLow": "adj_low",
    "adjClose": "adj_close",
    "adjVolume": "adj_volume",
    "splitFactor": "split_factor",
    "divCash": "dividend",
}


def _decimal(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return Decimal(value)
    return value


def map_record(raw: dict[str, Any]) -> dict[str, Any]:
    """One Tiingo row in the gate's shape. A missing field becomes None so the gate, not
    the adapter, decides that the record is malformed and records why."""
    record: dict[str, Any] = {}
    for vendor_key, key in FIELD_MAP.items():
        value = raw.get(vendor_key)
        if key == "date":
            record[key] = value[:10] if isinstance(value, str) else None
        else:
            record[key] = _decimal(value)
    return record


def parse_prices(body: str | bytes) -> list[dict[str, Any]]:
    """The rows of a prices response, mapped. Raises VendorProtocolError on a bad shape."""
    try:
        payload = json.loads(body, parse_float=Decimal)
    except ValueError as exc:
        raise VendorProtocolError("the response is not valid JSON") from exc
    if not isinstance(payload, list):
        raise VendorProtocolError(f"expected a JSON array, got {type(payload).__name__}")
    rows: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            raise VendorProtocolError(f"expected a JSON object per row, got {type(item).__name__}")
        rows.append(map_record(item))
    return rows


def _retry_after(response: httpx.Response) -> float | None:
    header = response.headers.get("Retry-After")
    if header is None:
        return None
    try:
        seconds = float(header)
    except ValueError:
        return None  # an HTTP date: fall back to the backoff schedule
    return min(max(seconds, 0.0), RETRY_AFTER_CAP_SECONDS)


class TiingoSource:
    name = "tiingo"

    def __init__(
        self,
        api_key: SecretStr,
        *,
        base_url: str = "https://api.tiingo.com",
        timeout_seconds: float = 30.0,
        budget: RequestBudget | None = None,
        purpose: str = "scheduled",
        client: httpx.AsyncClient | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        random: Callable[[], float] = random_module.random,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._budget = budget
        self._purpose = purpose
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)
        self._owns_client = client is None
        self._sleep = sleep
        self._random = random

    def __repr__(self) -> str:
        return f"TiingoSource(base_url={self._base_url!r}, purpose={self._purpose!r})"

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def _delay(self, attempt: int) -> float:
        """Exponential backoff for the retry after attempt number ``attempt`` (1-based)."""
        delay = min(BACKOFF_CAP_SECONDS, BACKOFF_BASE_SECONDS * float(2 ** (attempt - 1)))
        return delay * (1 - JITTER_FRACTION * self._random())

    async def fetch_daily(self, symbol: str, start: date, end: date) -> list[dict[str, Any]]:
        url = f"{self._base_url}/tiingo/daily/{quote(symbol, safe='')}/prices"
        params = {"startDate": start.isoformat(), "endDate": end.isoformat(), "format": "json"}
        headers = {"Authorization": f"Token {self._api_key.get_secret_value()}"}
        reason = "no attempt was made"
        for attempt in range(1, MAX_ATTEMPTS + 1):
            if self._budget is not None:
                await self._budget.acquire(self._purpose)
            retry_after: float | None = None
            try:
                response = await self._client.get(url, params=params, headers=headers)
            except httpx.TransportError as exc:  # timeouts and connection failures
                reason = type(exc).__name__
            else:
                status = response.status_code
                if status == 200:
                    return parse_prices(response.content)
                if status == 404:
                    raise UnknownSymbol(f"Tiingo does not know the symbol {symbol!r}")
                if status in (401, 403):
                    raise VendorAuthError(f"Tiingo refused the API key (HTTP {status})")
                if status != 429 and status < 500:
                    raise VendorProtocolError(f"unexpected HTTP {status} from Tiingo")
                reason = f"HTTP {status}"
                retry_after = _retry_after(response) if status == 429 else None
            log.warning(
                "tiingo request failed", extra={"symbol": symbol, "attempt": attempt, "why": reason}
            )
            if attempt < MAX_ATTEMPTS:
                await self._sleep(retry_after if retry_after is not None else self._delay(attempt))
        raise VendorTransientError(
            f"Tiingo did not answer for {symbol!r} after {MAX_ATTEMPTS} attempts ({reason})"
        )
