"""Shared token revocation (FR-PLT-002, FR-PLT-003).

Access tokens are short-lived and verified locally by every service, so a deactivated
user's or a demoted user's existing tokens must be cut off without each service asking
the Platform service. The Platform service records "tokens issued before this moment
are no longer valid" for the user in Redis; every service's :class:`Authenticator`
checks it on each request through :meth:`RevocationList.is_revoked`.

If Redis cannot be reached the check fails closed (HTTP 503) rather than letting a
possibly revoked token through (NFR-SEC-001).
"""

import time
import uuid

from redis.asyncio import Redis
from redis.exceptions import RedisError

from qs_template.auth import Principal
from qs_template.errors import ServiceError
from qs_template.logging import get_logger

log = get_logger(__name__)

KEY_PREFIX = "qs:auth:revoked-before:"


class RevocationList:
    def __init__(self, redis: Redis, *, max_token_lifetime_seconds: int = 86_400) -> None:
        self._redis = redis
        # After this long every token issued before the revocation has expired anyway
        self._ttl = max_token_lifetime_seconds

    @classmethod
    def from_url(cls, url: str, **kwargs: int) -> "RevocationList":
        return cls(Redis.from_url(url, socket_timeout=2, socket_connect_timeout=2), **kwargs)

    async def revoke_user(self, user_id: uuid.UUID) -> int:
        """Invalidate every token issued to ``user_id`` up to now; returns the cut-off.

        The cut-off is the next whole second, because token issue times are whole
        seconds: a token issued in the same second as the revocation is also refused.
        """
        cutoff = int(time.time()) + 1
        await self._redis.set(f"{KEY_PREFIX}{user_id}", cutoff, ex=self._ttl)
        return cutoff

    async def is_revoked(self, principal: Principal) -> bool:
        try:
            raw = await self._redis.get(f"{KEY_PREFIX}{principal.user_id}")
        except RedisError as exc:
            log.warning("revocation list unavailable", error=str(exc))
            raise ServiceError(
                503,
                "Service unavailable",
                "Tokens cannot be checked right now.",
                type_="urn:quantsim:problem:auth-unavailable",
            ) from exc
        return raw is not None and principal.issued_at < int(raw)

    async def ping(self) -> None:
        await self._redis.ping()

    async def close(self) -> None:
        await self._redis.aclose()
