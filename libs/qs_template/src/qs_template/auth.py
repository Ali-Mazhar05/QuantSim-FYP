"""Request authentication and role checks inside every service (FR-PLT-004, FR-PLT-005,
NFR-SEC-001).

The Platform service (M0) signs access tokens with its private key (RS256) and
publishes the public keys at its JWKS endpoint. Every other service verifies tokens
locally against those keys, cached in memory, so no request needs a call to M0. Each
service then decides, for its own data, whether the caller's role may proceed, and
fails closed: a missing, expired, forged or unverifiable token is refused.

    auth = Authenticator(settings)

    @router.get("/instruments")
    async def list_instruments(user: Principal = Depends(auth.principal)) -> ...

    @router.post("/instruments", dependencies=[Depends(auth.require(Role.ADMIN))])
    async def add_instrument(...) -> ...
"""

import asyncio
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, Any

import httpx
import jwt
import structlog
from fastapi import Depends, Header
from jwt import PyJWK

from qs_template.config import ServiceSettings
from qs_template.errors import ServiceError
from qs_template.logging import get_logger

log = get_logger(__name__)

ALGORITHM = "RS256"


class Role(StrEnum):
    """The fixed role set (NFR-INT-002); also constrained in platform_db."""

    ADMIN = "admin"
    QUANT = "quant"
    ANALYST = "analyst"
    VIEWER = "viewer"


@dataclass(frozen=True)
class Principal:
    """The authenticated user acting on a request."""

    user_id: uuid.UUID
    username: str
    role: Role
    token_id: str
    issued_at: int


def _unauthenticated(detail: str) -> ServiceError:
    return ServiceError(
        401,
        "Not authenticated",
        detail,
        type_="urn:quantsim:problem:not-authenticated",
        extra={},
    )


class JwksCache:
    """Public signing keys fetched from the Platform service and kept in memory.

    Keys are refreshed after ``ttl_seconds``, and immediately when a token names a key
    that is not cached (key rotation), at most once every ``min_refresh_seconds`` so a
    flood of bad tokens cannot hammer the Platform service.
    """

    def __init__(
        self,
        url: str,
        *,
        client: httpx.AsyncClient | None = None,
        ttl_seconds: float = 600,
        min_refresh_seconds: float = 30,
        timeout_seconds: float = 3,
    ) -> None:
        self._url = url
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)
        self._ttl = ttl_seconds
        self._min_refresh = min_refresh_seconds
        self._keys: dict[str, PyJWK] = {}
        self._fetched_at = 0.0
        self._lock = asyncio.Lock()

    async def key(self, kid: str) -> PyJWK:
        now = time.monotonic()
        stale = now - self._fetched_at > self._ttl
        if kid not in self._keys or stale:
            async with self._lock:
                may_refresh = time.monotonic() - self._fetched_at > self._min_refresh
                if (kid not in self._keys and may_refresh) or stale:
                    await self._refresh()
        try:
            return self._keys[kid]
        except KeyError:
            raise _unauthenticated("The token was signed with an unknown key.") from None

    async def _refresh(self) -> None:
        try:
            response = await self._client.get(self._url)
            response.raise_for_status()
            document: dict[str, Any] = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("could not fetch signing keys", url=self._url, error=str(exc))
            # Keep serving with the keys already cached; fail closed if there are none
            self._fetched_at = time.monotonic()
            if not self._keys:
                raise ServiceError(
                    503,
                    "Service unavailable",
                    "Tokens cannot be verified right now.",
                    type_="urn:quantsim:problem:auth-unavailable",
                ) from exc
            return
        keys: dict[str, PyJWK] = {}
        for entry in document.get("keys", []):
            if entry.get("kid") and entry.get("kty") == "RSA":
                keys[entry["kid"]] = PyJWK(entry, algorithm=ALGORITHM)
        self._keys = keys
        self._fetched_at = time.monotonic()

    async def close(self) -> None:
        await self._client.aclose()


class Authenticator:
    """Verifies bearer tokens and builds role checks for one service."""

    def __init__(
        self,
        settings: ServiceSettings,
        *,
        jwks: JwksCache | None = None,
        is_revoked: Callable[[Principal], Awaitable[bool]] | None = None,
    ) -> None:
        if jwks is None:
            if not settings.auth_jwks_url:
                raise ValueError("QS_AUTH_JWKS_URL must be set for services that authenticate")
            jwks = JwksCache(settings.auth_jwks_url)
        self._jwks = jwks
        self._issuer = settings.auth_issuer
        self._audience = settings.auth_audience
        self._leeway = settings.auth_leeway_seconds
        self._is_revoked = is_revoked

    async def verify(self, token: str) -> Principal:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.InvalidTokenError:
            raise _unauthenticated("The token is malformed.") from None
        if header.get("alg") != ALGORITHM or not header.get("kid"):
            raise _unauthenticated("The token is not signed with the expected algorithm.")

        key = await self._jwks.key(str(header["kid"]))
        try:
            claims: dict[str, Any] = jwt.decode(
                token,
                key=key.key,
                algorithms=[ALGORITHM],
                audience=self._audience,
                issuer=self._issuer,
                leeway=self._leeway,
                options={"require": ["exp", "iat", "sub", "jti", "iss", "aud"]},
            )
        except jwt.ExpiredSignatureError:
            raise _unauthenticated("The token has expired.") from None
        except jwt.InvalidTokenError:
            raise _unauthenticated("The token is not valid.") from None

        try:
            principal = Principal(
                user_id=uuid.UUID(str(claims["sub"])),
                username=str(claims.get("username", "")),
                role=Role(str(claims.get("role"))),
                token_id=str(claims["jti"]),
                issued_at=int(claims["iat"]),
            )
        except (ValueError, KeyError):
            raise _unauthenticated("The token does not name a valid user and role.") from None

        if self._is_revoked is not None and await self._is_revoked(principal):
            raise _unauthenticated("The token has been revoked.")
        return principal

    async def principal(self, authorization: Annotated[str | None, Header()] = None) -> Principal:
        """FastAPI dependency: the verified user behind the request's bearer token."""
        if not authorization:
            raise _unauthenticated("A bearer token is required.")
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise _unauthenticated("A bearer token is required.")
        principal = await self.verify(token.strip())
        structlog.contextvars.bind_contextvars(user_id=str(principal.user_id))
        return principal

    def require(self, *roles: Role) -> Callable[..., Awaitable[Principal]]:
        """FastAPI dependency that also checks the caller holds one of ``roles``."""
        allowed = frozenset(roles)

        async def check(principal: Annotated[Principal, Depends(self.principal)]) -> Principal:
            if principal.role not in allowed:
                raise ServiceError(
                    403,
                    "Forbidden",
                    "Your role does not allow this action.",
                    type_="urn:quantsim:problem:forbidden",
                )
            return principal

        return check
