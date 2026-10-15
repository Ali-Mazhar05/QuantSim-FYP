"""The shared hourly request budget (ingestion plan decisions D11 and D12).

Tiingo sends no rate-limit headers, and one free key allows 50 requests an hour for every
environment together. So the count lives in Redis, keyed by a hash of the API key (the key
itself never reaches Redis), as a fixed window of one hour.

``acquire`` answers at once: it takes a request or raises BudgetExhausted. It never sleeps
for the rest of the window; the caller defers the work. A scheduled run may use the whole
limit, while a backfill or manual run may only use ``limit - reserve_for_scheduled``, so a
backfill can never starve the daily run. When Redis cannot be reached the call is refused
(BudgetUnavailable): an unmetered call could spend the shared key.
"""

import hashlib
import time
from collections.abc import Callable
from typing import Any, Literal

from pydantic import SecretStr
from redis.exceptions import RedisError, WatchError

from qs_market.vendor.base import BudgetExhausted, BudgetUnavailable

Purpose = Literal["scheduled", "backfill"]
WINDOW_SECONDS = 3600
_RETRIES = 20


class RequestBudget:
    def __init__(
        self,
        redis: Any,
        api_key: SecretStr,
        *,
        limit: int = 45,
        reserve_for_scheduled: int = 40,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if limit < 1:
            raise ValueError("limit must be at least 1")
        if not 0 <= reserve_for_scheduled <= limit:
            raise ValueError("reserve_for_scheduled must be between 0 and limit")
        self._redis = redis
        digest = hashlib.sha256(api_key.get_secret_value().encode()).hexdigest()[:16]
        self._prefix = f"qs:tiingo:budget:{digest}"
        self._limit = limit
        self._reserve = reserve_for_scheduled
        self._clock = clock

    def __repr__(self) -> str:
        return f"RequestBudget(limit={self._limit}, reserve={self._reserve})"

    def _ceiling(self, purpose: str) -> int:
        return self._limit if purpose == "scheduled" else self._limit - self._reserve

    async def acquire(self, purpose: str = "scheduled") -> int:
        """Take one request from the current window; returns how many are left to this
        purpose. Raises BudgetExhausted or BudgetUnavailable."""
        ceiling = self._ceiling(purpose)
        window = int(self._clock() // WINDOW_SECONDS)
        key = f"{self._prefix}:{window}"
        try:
            for _ in range(_RETRIES):
                async with self._redis.pipeline(transaction=True) as pipe:
                    try:
                        await pipe.watch(key)
                        raw = await pipe.get(key)
                        used = int(raw) if raw is not None else 0
                        if used >= ceiling:
                            raise BudgetExhausted(
                                f"Tiingo budget spent for {purpose} requests "
                                f"({used} of {ceiling} this hour)"
                            )
                        pipe.multi()
                        pipe.incr(key)
                        pipe.expire(key, 2 * WINDOW_SECONDS)
                        await pipe.execute()
                        return ceiling - used - 1
                    except WatchError:
                        continue
        except (RedisError, OSError) as exc:
            raise BudgetUnavailable(
                f"the request budget store failed: {type(exc).__name__}"
            ) from exc
        raise BudgetUnavailable("the request budget is too contended to count")
