"""Request budget shared by every worker, kept in Redis.

A fixed one-hour window: each request takes a slot; when the hour's budget is spent the
caller waits for the next hour, or gives up if that is longer than it may wait (the run
then defers the remaining instruments instead of blocking for an hour).
"""

import asyncio
import time

from redis.asyncio import Redis

from qs_market.sources import RateLimited


class HourlyBudget:
    def __init__(self, redis: Redis, name: str, per_hour: int, *, max_wait_seconds: float = 0):
        self._redis = redis
        self._name = name
        self._per_hour = per_hour
        self._max_wait = max_wait_seconds

    async def acquire(self) -> None:
        while True:
            hour = int(time.time() // 3600)
            key = f"qs:market:budget:{self._name}:{hour}"
            used = int(await self._redis.incr(key))
            if used == 1:
                await self._redis.expire(key, 7200)
            if used <= self._per_hour:
                return
            wait = (hour + 1) * 3600 - time.time()
            if wait > self._max_wait:
                raise RateLimited(
                    f"{self._name}: hourly budget of {self._per_hour} requests used up",
                    retry_after=wait,
                )
            await asyncio.sleep(wait + 0.5)
