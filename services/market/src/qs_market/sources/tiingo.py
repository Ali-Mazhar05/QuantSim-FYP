"""Tiingo end-of-day prices (primary source, FR-MKT-002).

GET /tiingo/daily/<ticker>/prices?startDate=...&endDate=... returns one record per
session with raw and adjusted prices, ``divCash`` and ``splitFactor``. Every call goes
through the shared hourly budget, has explicit timeouts (NFR-PERF-005), and is retried
with exponential backoff and jitter on timeouts, 5xx and 429 (honouring Retry-After).
Unknown symbols and refused requests are not retried.
"""

import asyncio
import random
from datetime import date
from typing import Any

import httpx

from qs_market.sources import RateLimited, SymbolNotFound, VendorError, VendorRejected
from qs_market.sources.ratelimit import HourlyBudget
from qs_template.logging import get_logger

log = get_logger(__name__)


class TiingoSource:
    name = "tiingo"

    def __init__(
        self,
        api_key: str,
        *,
        budget: HourlyBudget,
        base_url: str = "https://api.tiingo.com",
        timeout_seconds: float = 30,
        max_attempts: int = 4,
        backoff_seconds: float = 1.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._budget = budget
        self._max_attempts = max_attempts
        self._backoff = backoff_seconds
        self._client = client or httpx.AsyncClient(
            base_url=base_url,
            timeout=httpx.Timeout(timeout_seconds, connect=5),
            headers={
                "Authorization": f"Token {api_key}",
                "Content-Type": "application/json",
                "User-Agent": "QuantSim/0.1 (market-data ingestion)",
            },
        )

    async def fetch_daily(self, symbol: str, start: date, end: date) -> list[dict[str, Any]]:
        path = f"/tiingo/daily/{symbol.lower()}/prices"
        params = {"startDate": start.isoformat(), "endDate": end.isoformat(), "format": "json"}
        last_error: VendorError | None = None
        for attempt in range(1, self._max_attempts + 1):
            await self._budget.acquire()
            try:
                return await self._get(path, params, symbol)
            except VendorError as exc:
                if not exc.retryable or attempt == self._max_attempts:
                    raise
                last_error = exc
                delay = exc.retry_after or self._backoff * 2 ** (attempt - 1)
                delay += random.uniform(0, self._backoff)  # noqa: S311 - jitter, not crypto
                log.warning(
                    "vendor call failed, retrying",
                    source=self.name,
                    symbol=symbol,
                    attempt=attempt,
                    delay_seconds=round(delay, 1),
                    error=str(exc),
                )
                await asyncio.sleep(delay)
        raise last_error or VendorError("unreachable")

    async def _get(self, path: str, params: dict[str, str], symbol: str) -> list[dict[str, Any]]:
        try:
            response = await self._client.get(path, params=params)
        except httpx.TimeoutException as exc:
            raise VendorError(f"timeout calling Tiingo for {symbol}") from exc
        except httpx.HTTPError as exc:
            raise VendorError(f"network error calling Tiingo for {symbol}: {exc}") from exc

        if response.status_code == 404:
            raise SymbolNotFound(f"Tiingo does not know {symbol}")
        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After")
            raise RateLimited(
                "Tiingo rate limit reached",
                retry_after=float(retry_after) if retry_after and retry_after.isdigit() else None,
            )
        if response.status_code >= 500:
            raise VendorError(f"Tiingo returned {response.status_code} for {symbol}")
        if response.status_code >= 400:
            raise VendorRejected(f"Tiingo refused the request for {symbol} ({response.status_code})")
        try:
            body = response.json()
        except ValueError as exc:
            raise VendorError(f"Tiingo returned invalid JSON for {symbol}") from exc
        if not isinstance(body, list):
            raise VendorError(f"unexpected Tiingo response for {symbol}")
        return [record for record in body if isinstance(record, dict)]

    def normalise(self, record: dict[str, Any]) -> dict[str, Any]:
        return {
            "date": record.get("date"),
            "open": record.get("open"),
            "high": record.get("high"),
            "low": record.get("low"),
            "close": record.get("close"),
            "volume": record.get("volume"),
            "adj_close": record.get("adjClose"),
            "split_factor": record.get("splitFactor"),
            "dividend": record.get("divCash"),
        }

    async def close(self) -> None:
        await self._client.aclose()
