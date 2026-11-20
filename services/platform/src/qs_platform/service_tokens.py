"""Service tokens for calls between services (ADR 09, client credentials).

A service that calls another one (for example a trading job reading market data long
after it was submitted) sends its client id (its service name) and client secret to
``POST /api/platform/service-tokens`` and gets a short-lived access token, signed with the
same key as user tokens and verified the same way by every service.

- The token names a service, never a user: ``sub="service:<name>"`` and
  ``kind="service"``, with the viewer role (service calls only read, one hop deep).
- Secrets come from ``QS_SERVICE_CLIENT_SECRETS``; only their SHA-256 is kept in memory,
  compared in constant time, and an unknown client costs the same as a wrong secret.
- Repeated bad secrets from one address block that address for a while, like failed
  sign-ins; the limit store failing closes the route (503).
- Every issue and every refusal is logged with the service name and the token id; the
  token and the secret are never logged.
"""

import hashlib
import hmac
import time
import uuid

from qs_platform.keys import SigningKeys
from qs_platform.limits import RateLimiter, too_many
from qs_platform.schemas import ServiceTokenResponse
from qs_platform.settings import PlatformSettings
from qs_template.auth import SERVICE_SUBJECT_PREFIX, SERVICE_TOKEN_KIND, Role
from qs_template.errors import ServiceError
from qs_template.logging import get_logger

log = get_logger(__name__)

INVALID_CLIENT = ServiceError(
    401,
    "Invalid client",
    "The client id or secret is incorrect.",
    type_="urn:quantsim:problem:invalid-client",
)

# Compared against when the client is unknown, so the answer takes the same time
_NO_CLIENT = hashlib.sha256(b"no such client").digest()


class ServiceTokenIssuer:
    def __init__(self, settings: PlatformSettings, keys: SigningKeys, limiter: RateLimiter) -> None:
        self._settings = settings
        self._keys = keys
        self._limiter = limiter
        self._digests = settings.service_client_digests

    async def issue(self, client_id: str, client_secret: str, client: str) -> ServiceTokenResponse:
        limit_key = f"service-token:{client}"
        limit = self._settings.login_max_failures
        wait = await self._limiter.blocked(limit_key, limit)
        if wait is not None:
            log.warning("service token refused: address blocked", client_id=client_id)
            raise too_many(wait)

        expected = self._digests.get(client_id)
        given = hashlib.sha256(client_secret.encode()).digest()
        valid = hmac.compare_digest(given, expected or _NO_CLIENT) and expected is not None
        if not valid:
            log.warning("service token refused: bad client credentials", client_id=client_id)
            await self._limiter.hit(limit_key, limit, self._settings.login_lockout_seconds)
            raise INVALID_CLIENT

        now_ms = int(time.time() * 1000)
        now = now_ms // 1000
        ttl = self._settings.service_token_ttl_seconds
        token_id = uuid.uuid4().hex
        claims = {
            "iss": self._settings.auth_issuer,
            "aud": self._settings.auth_audience,
            "sub": f"{SERVICE_SUBJECT_PREFIX}{client_id}",
            "kind": SERVICE_TOKEN_KIND,
            "role": Role.VIEWER.value,
            "jti": token_id,
            "iat": now,
            "iat_ms": now_ms,
            "exp": now + ttl,
        }
        log.info("service token issued", client_id=client_id, token_id=token_id, expires_in=ttl)
        return ServiceTokenResponse(access_token=self._keys.sign(claims), expires_in=ttl)
