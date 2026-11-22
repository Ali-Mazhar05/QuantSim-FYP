"""Service-to-service calls (platform kit K3, A-FR-19).

Background workers call other services with no user behind the request, for example a
trading engine job reading market ticks half an hour after it was submitted. They use a
:class:`ServiceClient`, which adds a service token, a per-request timeout, retries with
backoff and a circuit breaker, and turns every failure into one controlled
:class:`ServiceCallError`, so a job fails cleanly instead of hanging or crashing.

    client = ServiceClient(
        "http://market:8000",
        caller="trading",
        tokens=service_tokens_from_settings(settings),
    )
    page = await client.get_json("/api/market/environments/env-1/ticks", params={"after_seq": 0})
    await client.close()

Tokens (ADR 09). :func:`service_tokens_from_settings` picks the provider, so a service
switches in one place:

- :class:`ClientCredentialsToken` when ``QS_SERVICE_TOKEN_URL`` and
  ``QS_SERVICE_CLIENT_SECRET`` are set: short-lived tokens issued by the Platform service
  for this service (client id ``QS_SERVICE_CLIENT_ID``, default the service name), cached
  and renewed before they expire.
- otherwise :class:`StaticServiceToken`, the DEV-only shared secret ``QS_SERVICE_TOKEN``.
  It refuses to load outside the ``local`` and ``dev`` environments.

The receiving service accepts either through :class:`qs_template.auth.Authenticator` as a
read-only service principal.

Errors raised (all :class:`ServiceCallError`, a :class:`~qs_template.errors.ServiceError`):

=====================================  ======  ==========================================
type                                   status  when
=====================================  ======  ==========================================
``urn:quantsim:problem:upstream-down``  503     retries exhausted (connect error, timeout,
                                                429, 502, 503, 504)
``urn:quantsim:problem:circuit-open``   503     too many recent failures; call not sent
``urn:quantsim:problem:upstream-error`` 502     the provider answered 4xx or 500; its
                                                status and problem body are in ``extra``
=====================================  ======  ==========================================
"""

import asyncio
import random
import time
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Protocol

import httpx
import structlog
from pydantic import SecretStr

from qs_template.config import ServiceSettings
from qs_template.errors import ServiceError
from qs_template.logging import get_logger

log = get_logger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"
CALLER_HEADER = "X-Calling-Service"
IDEMPOTENCY_HEADER = "Idempotency-Key"
# Environments where the shared DEV token may be used
STATIC_TOKEN_ENVIRONMENTS = frozenset({"local", "dev"})
RETRYABLE_STATUS = frozenset({429, 502, 503, 504})
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


class ServiceCallError(ServiceError):
    """A call to another service failed; ``extra`` names the target and the cause."""


class TokenProvider(Protocol):
    async def token(self) -> str:
        """A bearer token the target service accepts for the calling service."""
        ...


class StaticServiceToken:
    """The DEV-only shared service token (until real service tokens, 2 Dec)."""

    def __init__(self, token: SecretStr, *, environment: str) -> None:
        if environment not in STATIC_TOKEN_ENVIRONMENTS:
            raise ValueError(
                f"the static service token is for local and dev only, not {environment!r}"
            )
        if len(token.get_secret_value()) < 32:
            raise ValueError("the static service token must be at least 32 characters")
        self._token = token

    @classmethod
    def from_settings(cls, settings: ServiceSettings) -> "StaticServiceToken":
        if settings.service_token is None:
            raise ValueError("QS_SERVICE_TOKEN must be set for services that call others")
        return cls(settings.service_token, environment=settings.environment)

    async def token(self) -> str:
        return self._token.get_secret_value()


class ClientCredentialsToken:
    """Short-lived service tokens from the Platform service (client credentials).

    The token is cached and fetched again ``refresh_margin_seconds`` before it expires
    (at most half its lifetime), so a job that calls another service long after it
    started always sends a valid token. Concurrent callers share one fetch. If a renewal
    fails while the cached token is still valid, the cached token is used.
    """

    def __init__(
        self,
        token_url: str,
        *,
        client_id: str,
        client_secret: SecretStr,
        refresh_margin_seconds: float = 60.0,
        timeout_seconds: float = 5.0,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not client_secret.get_secret_value():
            raise ValueError("the service client secret must not be empty")
        self._url = token_url
        self._client_id = client_id
        self._secret = client_secret
        self._margin = refresh_margin_seconds
        self._clock = clock
        self._client = httpx.AsyncClient(timeout=timeout_seconds, transport=transport)
        self._lock = asyncio.Lock()
        self._token: str | None = None
        self._expires_at = 0.0
        self._refresh_at = 0.0

    @classmethod
    def from_settings(cls, settings: ServiceSettings, **kwargs: Any) -> "ClientCredentialsToken":
        if not settings.service_token_url or settings.service_client_secret is None:
            raise ValueError("QS_SERVICE_TOKEN_URL and QS_SERVICE_CLIENT_SECRET must both be set")
        return cls(
            settings.service_token_url,
            client_id=settings.service_client_id or settings.service_name,
            client_secret=settings.service_client_secret,
            **kwargs,
        )

    async def token(self) -> str:
        if self._token is not None and self._clock() < self._refresh_at:
            return self._token
        async with self._lock:
            # Another caller may have renewed it while this one waited
            if self._token is not None and self._clock() < self._refresh_at:
                return self._token
            try:
                return await self._fetch()
            except ServiceCallError:
                if self._token is not None and self._clock() < self._expires_at:
                    log.warning("service token renewal failed; using the cached token")
                    return self._token
                raise

    async def _fetch(self) -> str:
        started = self._clock()
        try:
            response = await self._client.post(
                self._url,
                json={
                    "grant_type": "client_credentials",
                    "client_id": self._client_id,
                    "client_secret": self._secret.get_secret_value(),
                },
            )
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise self._unavailable(f"{type(exc).__name__}: {exc}") from exc
        if response.status_code != 200:
            raise self._unavailable(f"HTTP {response.status_code}")
        try:
            body = response.json()
            token = str(body["access_token"])
            lifetime = float(body["expires_in"])
        except (ValueError, KeyError, TypeError) as exc:
            raise self._unavailable("the token response is malformed") from exc
        self._token = token
        self._expires_at = started + lifetime
        self._refresh_at = self._expires_at - min(self._margin, lifetime / 2)
        return token

    def _unavailable(self, cause: str) -> ServiceCallError:
        return ServiceCallError(
            503,
            "Service unavailable",
            f"No service token for {self._client_id}: {cause}",
            type_="urn:quantsim:problem:service-token-unavailable",
            extra={"target": self._url},
        )

    async def close(self) -> None:
        await self._client.aclose()


def service_tokens_from_settings(settings: ServiceSettings) -> TokenProvider:
    """The token provider a calling service uses: real platform-issued tokens when
    configured, else the DEV static token, else an error naming what to set."""
    if settings.service_token_url and settings.service_client_secret is not None:
        return ClientCredentialsToken.from_settings(settings)
    if settings.service_client_secret is not None:
        raise ValueError("QS_SERVICE_CLIENT_SECRET is set but QS_SERVICE_TOKEN_URL is not")
    if settings.service_token is not None:
        return StaticServiceToken.from_settings(settings)
    raise ValueError(
        "set QS_SERVICE_TOKEN_URL and QS_SERVICE_CLIENT_SECRET (or, in local and dev, "
        "QS_SERVICE_TOKEN) for services that call others"
    )


class CircuitBreaker:
    """Fails fast after ``failure_threshold`` consecutive failures.

    Open: calls are refused for ``reset_after_seconds``. Then one trial call is let
    through (half open); success closes the circuit, failure opens it again.
    """

    def __init__(
        self,
        *,
        failure_threshold: int = 5,
        reset_after_seconds: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if failure_threshold < 1:
            raise ValueError("failure_threshold must be at least 1")
        self._threshold = failure_threshold
        self._reset_after = reset_after_seconds
        self._clock = clock
        self._failures = 0
        self._opened_at: float | None = None
        self._trial_running = False

    @property
    def state(self) -> str:
        if self._opened_at is None:
            return "closed"
        if self._clock() - self._opened_at >= self._reset_after:
            return "half-open"
        return "open"

    def allow(self) -> bool:
        state = self.state
        if state == "closed":
            return True
        if state == "half-open" and not self._trial_running:
            self._trial_running = True
            return True
        return False

    def record_success(self) -> None:
        self._failures = 0
        self._opened_at = None
        self._trial_running = False

    def record_failure(self) -> None:
        self._failures += 1
        if self._trial_running or self._failures >= self._threshold:
            self._opened_at = self._clock()
        self._trial_running = False


class ServiceClient:
    """Calls one target service on behalf of ``caller``.

    Only safe methods (GET, HEAD, OPTIONS) and requests that carry an idempotency key are
    retried, so a retry can never apply a write twice.
    """

    def __init__(
        self,
        base_url: str,
        *,
        caller: str,
        tokens: TokenProvider,
        timeout_seconds: float = 10.0,
        connect_timeout_seconds: float = 3.0,
        retries: int = 3,
        backoff_seconds: float = 0.5,
        max_backoff_seconds: float = 8.0,
        breaker: CircuitBreaker | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if retries < 0:
            raise ValueError("retries cannot be negative")
        self._target = base_url.rstrip("/")
        self._caller = caller
        self._tokens = tokens
        self._retries = retries
        self._backoff = backoff_seconds
        self._max_backoff = max_backoff_seconds
        self._breaker = breaker or CircuitBreaker()
        self._sleep = sleep
        self._client = httpx.AsyncClient(
            base_url=self._target,
            timeout=httpx.Timeout(timeout_seconds, connect=connect_timeout_seconds),
            transport=transport,
        )

    @property
    def breaker(self) -> CircuitBreaker:
        return self._breaker

    async def get(self, path: str, *, params: Mapping[str, Any] | None = None) -> httpx.Response:
        return await self.request("GET", path, params=params)

    async def get_json(self, path: str, *, params: Mapping[str, Any] | None = None) -> Any:
        """GET ``path`` and return its JSON body."""
        return (await self.get(path, params=params)).json()

    async def post(
        self,
        path: str,
        *,
        json: Any = None,
        idempotency_key: str | None = None,
    ) -> httpx.Response:
        return await self.request("POST", path, json=json, idempotency_key=idempotency_key)

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any = None,
        idempotency_key: str | None = None,
    ) -> httpx.Response:
        """Sends one request, retrying what is safe to retry. Returns a 2xx or 3xx
        response; every failure raises :class:`ServiceCallError`."""
        method = method.upper()
        retryable = method in SAFE_METHODS or idempotency_key is not None
        attempts = 1 + (self._retries if retryable else 0)
        last_cause = ""
        for attempt in range(1, attempts + 1):
            if not self._breaker.allow():
                raise self._error(
                    503,
                    "circuit-open",
                    f"{self._target} failed too often recently; the call was not sent.",
                    path,
                )
            try:
                response = await self._client.request(
                    method,
                    path,
                    params=params,
                    json=json,
                    headers=await self._headers(idempotency_key),
                )
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                self._breaker.record_failure()
                last_cause = f"{type(exc).__name__}: {exc}"
            else:
                if response.status_code in RETRYABLE_STATUS:
                    self._breaker.record_failure()
                    last_cause = f"HTTP {response.status_code}"
                elif response.status_code >= 400:
                    # The provider is up and answered: not a reason to open the circuit
                    # unless it is a server error
                    if response.status_code >= 500:
                        self._breaker.record_failure()
                    else:
                        self._breaker.record_success()
                    raise self._upstream_error(response, path)
                else:
                    self._breaker.record_success()
                    return response
            if attempt < attempts:
                delay = self._delay(attempt)
                log.warning(
                    "service call failed; retrying",
                    target=self._target,
                    path=path,
                    attempt=attempt,
                    cause=last_cause,
                    retry_in=round(delay, 2),
                )
                await self._sleep(delay)
        raise self._error(
            503,
            "upstream-down",
            f"{self._target} did not answer after {attempts} attempt(s): {last_cause}",
            path,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def _headers(self, idempotency_key: str | None) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {await self._tokens.token()}",
            CALLER_HEADER: self._caller,
        }
        request_id = structlog.contextvars.get_contextvars().get("request_id")
        if request_id:
            headers[REQUEST_ID_HEADER] = str(request_id)
        if idempotency_key is not None:
            headers[IDEMPOTENCY_HEADER] = idempotency_key
        return headers

    def _delay(self, attempt: int) -> float:
        """Exponential backoff with full jitter, capped."""
        ceiling = min(self._max_backoff, self._backoff * 2 ** (attempt - 1))
        return float(random.uniform(0, ceiling))  # noqa: S311 - jitter, not security

    def _error(self, status: int, kind: str, detail: str, path: str) -> ServiceCallError:
        return ServiceCallError(
            status,
            "Service unavailable",
            detail,
            type_=f"urn:quantsim:problem:{kind}",
            extra={"target": self._target, "path": path},
        )

    def _upstream_error(self, response: httpx.Response, path: str) -> ServiceCallError:
        try:
            body: Any = response.json()
        except ValueError:
            body = response.text[:500]
        return ServiceCallError(
            502,
            "Upstream error",
            f"{self._target} answered {response.status_code} for {path}.",
            type_="urn:quantsim:problem:upstream-error",
            extra={
                "target": self._target,
                "path": path,
                "upstream_status": response.status_code,
                "upstream_body": body,
            },
        )
