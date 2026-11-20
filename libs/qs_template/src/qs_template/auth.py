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
import hmac
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, Any, Protocol

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


class Capability(StrEnum):
    """What a role may do. Names match the POC frontend's capability map
    (frontend/src/demo/permissions.ts) so the UI hides and disables exactly what the
    backend refuses; the backend-only ones at the end have no POC control."""

    VIEW_DASHBOARDS = "view_dashboards"
    VIEW_REPORTS = "view_reports"
    VIEW_ALERTS = "view_alerts"
    RUN_STRESS_TEST = "run_stress_test"
    RUN_TDA = "run_tda"
    COMPUTE_METRICS = "compute_metrics"
    CONFIGURE_DASHBOARDS = "configure_dashboards"
    CREATE_ALERTS = "create_alerts"
    CREATE_STRATEGIES = "create_strategies"
    CALIBRATE_MODELS = "calibrate_models"
    LAUNCH_SIMULATIONS = "launch_simulations"
    CREATE_PORTFOLIOS = "create_portfolios"
    MANAGE_MODELS = "manage_models"
    MANAGE_USERS = "manage_users"
    MANAGE_ROLES = "manage_roles"
    MANAGE_INSTRUMENTS = "manage_instruments"
    CONFIGURE_SYSTEM = "configure_system"
    # Backend-only
    VIEW_MARKET_DATA = "view_market_data"
    VIEW_INGESTION_RUNS = "view_ingestion_runs"
    CREATE_MARKET_ENVIRONMENTS = "create_market_environments"
    TRIGGER_INGESTION = "trigger_ingestion"
    BACKFILL_MARKET_DATA = "backfill_market_data"
    VIEW_AUDIT_LOG = "view_audit_log"


_VIEWER = frozenset(
    {
        Capability.VIEW_DASHBOARDS,
        Capability.VIEW_REPORTS,
        Capability.VIEW_ALERTS,
        Capability.VIEW_MARKET_DATA,
    }
)
_ANALYST = _VIEWER | {
    Capability.RUN_STRESS_TEST,
    Capability.RUN_TDA,
    Capability.COMPUTE_METRICS,
    Capability.CONFIGURE_DASHBOARDS,
    Capability.CREATE_ALERTS,
    Capability.VIEW_INGESTION_RUNS,
}
_QUANT = _ANALYST | {
    Capability.CREATE_STRATEGIES,
    Capability.CALIBRATE_MODELS,
    Capability.LAUNCH_SIMULATIONS,
    Capability.CREATE_PORTFOLIOS,
    Capability.MANAGE_MODELS,
    Capability.CREATE_MARKET_ENVIRONMENTS,
    Capability.TRIGGER_INGESTION,
}
_ADMIN = _QUANT | {
    Capability.MANAGE_USERS,
    Capability.MANAGE_ROLES,
    Capability.MANAGE_INSTRUMENTS,
    Capability.CONFIGURE_SYSTEM,
    Capability.BACKFILL_MARKET_DATA,
    Capability.VIEW_AUDIT_LOG,
}

# The authoritative role matrix (SPEC section 1): each role adds to the one below it
ROLE_CAPABILITIES: dict[Role, frozenset[Capability]] = {
    Role.VIEWER: _VIEWER,
    Role.ANALYST: frozenset(_ANALYST),
    Role.QUANT: frozenset(_QUANT),
    Role.ADMIN: frozenset(_ADMIN),
}

# Order used for "preview as an equal or lower role" in the frontend
ROLE_RANK: dict[Role, int] = {Role.VIEWER: 0, Role.ANALYST: 1, Role.QUANT: 2, Role.ADMIN: 3}


def can(role: Role, capability: Capability) -> bool:
    return capability in ROLE_CAPABILITIES[role]


@dataclass(frozen=True)
class Principal:
    """The authenticated user acting on a request."""

    user_id: uuid.UUID
    username: str
    role: Role
    token_id: str
    issued_at: int
    # Millisecond issue time ("iat_ms" claim, falling back to iat), so a revocation can
    # cut off exactly the tokens issued before it
    issued_at_ms: int = 0
    # True for another service calling (no user behind it): with a platform-issued
    # service token, or with the DEV static token
    is_service: bool = False
    # The calling service, when a platform-issued service token names it
    service_name: str | None = None

    def __post_init__(self) -> None:
        if not self.issued_at_ms:
            object.__setattr__(self, "issued_at_ms", self.issued_at * 1000)


# Environments where the shared DEV service token is accepted (kit K3)
SERVICE_TOKEN_ENVIRONMENTS = frozenset({"local", "dev"})

# Who a call made with the DEV service token acts as: read-only, like a viewer, because
# service calls only read other services' data (one hop deep)
_SERVICE_ID = "urn:quantsim:service"
SERVICE_PRINCIPAL = Principal(
    user_id=uuid.uuid5(uuid.NAMESPACE_URL, _SERVICE_ID),
    username="service",
    role=Role.VIEWER,
    token_id=_SERVICE_ID,
    issued_at=0,
    is_service=True,
)


# Platform-issued service tokens (ADR 09). They carry kind="service" and
# sub="service:<name>"; user tokens carry no kind and a user id as sub, so neither can be
# taken for the other.
SERVICE_TOKEN_KIND = "service"  # noqa: S105 - a claim value, not a secret
SERVICE_SUBJECT_PREFIX = "service:"
# The services that may hold a service token
KNOWN_SERVICES = frozenset({"platform", "market", "simulation", "trading", "risk"})


def service_principal(
    name: str, *, token_id: str, issued_at: int, issued_at_ms: int = 0
) -> Principal:
    """Who a call made with a service token of ``name`` acts as: read-only, like a
    viewer. Its id is fixed per service, so revoking it cuts that service's tokens off."""
    return Principal(
        user_id=uuid.uuid5(uuid.NAMESPACE_URL, f"{_SERVICE_ID}:{name}"),
        username=f"{SERVICE_SUBJECT_PREFIX}{name}",
        role=Role.VIEWER,
        token_id=token_id,
        issued_at=issued_at,
        issued_at_ms=issued_at_ms,
        is_service=True,
        service_name=name,
    )


def _unauthenticated(detail: str) -> ServiceError:
    return ServiceError(
        401,
        "Not authenticated",
        detail,
        type_="urn:quantsim:problem:not-authenticated",
        extra={},
    )


class KeySource(Protocol):
    async def key(self, kid: str) -> PyJWK:
        """The public key with id ``kid``; raises a 401 ServiceError when unknown."""


class StaticKeys:
    """Keys held in process, for the Platform service, which issues the tokens."""

    def __init__(self, jwks: dict[str, Any]) -> None:
        self._keys = {
            entry["kid"]: PyJWK(entry, algorithm=ALGORITHM)
            for entry in jwks.get("keys", [])
            if entry.get("kid")
        }

    async def key(self, kid: str) -> PyJWK:
        try:
            return self._keys[kid]
        except KeyError:
            raise _unauthenticated("The token was signed with an unknown key.") from None


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
        jwks: KeySource | None = None,
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
        self._service_token: bytes | None = None
        if settings.service_token is not None:
            if settings.environment not in SERVICE_TOKEN_ENVIRONMENTS:
                raise ValueError(
                    "QS_SERVICE_TOKEN is for local and dev only, "
                    f"not {settings.environment!r}; remove it from this environment"
                )
            self._service_token = settings.service_token.get_secret_value().encode()

    async def verify(self, token: str) -> Principal:
        if self._service_token is not None and hmac.compare_digest(
            token.encode(), self._service_token
        ):
            return SERVICE_PRINCIPAL
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

        if "kind" in claims:
            principal = self._service_principal(claims)
        else:
            try:
                principal = Principal(
                    user_id=uuid.UUID(str(claims["sub"])),
                    username=str(claims.get("username", "")),
                    role=Role(str(claims.get("role"))),
                    token_id=str(claims["jti"]),
                    issued_at=int(claims["iat"]),
                    issued_at_ms=int(claims.get("iat_ms") or int(claims["iat"]) * 1000),
                )
            except (ValueError, KeyError):
                raise _unauthenticated("The token does not name a valid user and role.") from None

        if self._is_revoked is not None and await self._is_revoked(principal):
            raise _unauthenticated("The token has been revoked.")
        return principal

    @staticmethod
    def _service_principal(claims: dict[str, Any]) -> Principal:
        """A platform-issued service token: always the viewer role, whatever it claims."""
        subject = str(claims["sub"])
        name = subject.removeprefix(SERVICE_SUBJECT_PREFIX)
        if (
            claims.get("kind") != SERVICE_TOKEN_KIND
            or not subject.startswith(SERVICE_SUBJECT_PREFIX)
            or name not in KNOWN_SERVICES
            or claims.get("role") != Role.VIEWER.value
        ):
            raise _unauthenticated("The token does not name a known service.")
        try:
            return service_principal(
                name,
                token_id=str(claims["jti"]),
                issued_at=int(claims["iat"]),
                issued_at_ms=int(claims.get("iat_ms") or int(claims["iat"]) * 1000),
            )
        except ValueError:
            raise _unauthenticated("The token does not name a known service.") from None

    async def principal(self, authorization: Annotated[str | None, Header()] = None) -> Principal:
        """FastAPI dependency: the verified user behind the request's bearer token."""
        if not authorization:
            raise _unauthenticated("A bearer token is required.")
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise _unauthenticated("A bearer token is required.")
        principal = await self.verify(token.strip())
        if principal.service_name is not None:
            structlog.contextvars.bind_contextvars(calling_service=principal.service_name)
        else:
            structlog.contextvars.bind_contextvars(user_id=str(principal.user_id))
        return principal

    def require_capability(self, *capabilities: Capability) -> Callable[..., Awaitable[Principal]]:
        """FastAPI dependency that also checks the caller's role grants every capability."""
        needed = frozenset(capabilities)

        async def check(principal: Annotated[Principal, Depends(self.principal)]) -> Principal:
            if not needed <= ROLE_CAPABILITIES[principal.role]:
                raise ServiceError(
                    403,
                    "Forbidden",
                    "Your role does not allow this action.",
                    type_="urn:quantsim:problem:forbidden",
                )
            return principal

        return check

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
