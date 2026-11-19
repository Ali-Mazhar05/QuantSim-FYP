"""Fixed-window counters in Redis for the public account routes (design D7).

They fail closed: if Redis cannot be reached the route answers 503 instead of running
without a limit.
"""

from redis.asyncio import Redis
from redis.exceptions import RedisError

from qs_template.errors import ServiceError
from qs_template.logging import get_logger

log = get_logger(__name__)

KEY_PREFIX = "qs:platform:limit:"

UNAVAILABLE = ServiceError(
    503,
    "Service unavailable",
    "This can't be done right now. Try again in a minute.",
    type_="urn:quantsim:problem:limits-unavailable",
)


class RateLimiter:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    @classmethod
    def from_url(cls, url: str) -> "RateLimiter":
        return cls(Redis.from_url(url, socket_timeout=2, socket_connect_timeout=2))

    async def hit(self, key: str, limit: int, window_seconds: int) -> int | None:
        """Count one attempt; returns the seconds to wait when over the limit, else None."""
        name = f"{KEY_PREFIX}{key}"
        try:
            count = int(await self._redis.incr(name))
            if count == 1:
                await self._redis.expire(name, window_seconds)
            if count <= limit:
                return None
            ttl = int(await self._redis.ttl(name))
        except RedisError as exc:
            log.warning("rate limit store unavailable", error=str(exc))
            raise UNAVAILABLE from exc
        return ttl if ttl > 0 else window_seconds

    async def close(self) -> None:
        await self._redis.aclose()


def too_many(retry_after_seconds: int) -> ServiceError:
    return ServiceError(
        429,
        "Too many attempts",
        "Too many attempts from this address. Try again later.",
        type_="urn:quantsim:problem:rate-limited",
        extra={"retry_after_seconds": retry_after_seconds},
    )
