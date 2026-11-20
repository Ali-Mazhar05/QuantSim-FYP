"""The small HTTP client the market feed adapters (task A17) read through.

The adapters in :mod:`qs_trading.adapters.http_environment` depend only on
:class:`FeedClient`: one ``GET`` that returns the status, the headers and the decoded JSON
body, whatever the status. Deciding what a status means (a permanent or a transient
failure) is the adapter's job, so a test can serve the contract with ``httpx.MockTransport``
and a later client can be swapped in without touching the adapters.

:class:`HttpxFeedClient` is the implementation used today: an ``httpx.AsyncClient`` on the
provider's base URL that sends ``Authorization: Bearer <token>`` from a
:class:`TokenProvider`. A connection error or a timeout raises :class:`FeedUnavailable`,
which is transient (a retry may succeed).

**K3.** Once the platform kit's ``ServiceClient`` (``qs_template.service_client``, K3) is on
``develop``, it replaces :class:`HttpxFeedClient` (see the K3 plug-in point at the end of
this module): it adds retries with backoff, a circuit breaker and the request id, and its
``StaticServiceToken`` replaces :class:`StaticToken`. The adapters do not change.
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx
from pydantic import SecretStr

from qs_trading.ports.market_environment import MarketEnvironmentError

__all__ = [
    "CALLER",
    "FeedClient",
    "FeedResponse",
    "FeedUnavailable",
    "HttpxFeedClient",
    "StaticToken",
    "TokenProvider",
]

CALLER = "trading"
"""Sent as ``X-Calling-Service``, the header K3's ``ServiceClient`` sends."""


class FeedUnavailable(MarketEnvironmentError):
    """The feed could not be read now (connection error, timeout, 429 or 5xx); transient,
    so the job is retried."""


@dataclass(frozen=True, slots=True)
class FeedResponse:
    """One answer of a feed: the status, the headers (names in lower case) and the JSON
    body (``None`` when the body is empty or not JSON)."""

    status: int
    headers: Mapping[str, str] = field(default_factory=dict)
    body: Any = None

    def header(self, name: str) -> str | None:
        return self.headers.get(name.lower())


class FeedClient(Protocol):
    """Reads one URL path of a provider service."""

    async def get(self, path: str, params: Mapping[str, int | str] | None = None) -> FeedResponse:
        """``GET path``; answers every HTTP status, raises :class:`FeedUnavailable` only
        when no answer came (connection error or timeout)."""
        ...


class TokenProvider(Protocol):
    """A bearer token the provider accepts for the trading service (K3's protocol)."""

    async def token(self) -> str: ...


class StaticToken:
    """The DEV service token (``QS_SERVICE_TOKEN``) as a :class:`TokenProvider`. The value
    is kept as a secret and never shown by ``repr`` or logs.

    Replaced by K3's ``StaticServiceToken`` once #85 is merged."""

    def __init__(self, token: SecretStr) -> None:
        if not token.get_secret_value():
            raise ValueError("the service token is empty")
        self._token = token

    def __repr__(self) -> str:
        return "StaticToken(**********)"

    async def token(self) -> str:
        return self._token.get_secret_value()


class HttpxFeedClient:
    """A :class:`FeedClient` over ``httpx.AsyncClient``. ``transport`` is for tests
    (``httpx.MockTransport``)."""

    def __init__(
        self,
        base_url: str,
        tokens: TokenProvider,
        *,
        timeout_seconds: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._tokens = tokens
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(timeout_seconds),
            transport=transport,
            follow_redirects=False,
        )

    async def get(self, path: str, params: Mapping[str, int | str] | None = None) -> FeedResponse:
        headers = {
            "Authorization": f"Bearer {await self._tokens.token()}",
            "Accept": "application/json",
            "X-Calling-Service": CALLER,
        }
        try:
            response = await self._client.get(path, params=dict(params or {}), headers=headers)
        except httpx.TimeoutException as exc:
            raise FeedUnavailable(f"{self.base_url}{path} timed out: {exc!r}") from None
        except httpx.TransportError as exc:
            raise FeedUnavailable(f"{self.base_url}{path} is unreachable: {exc!r}") from None
        try:
            body = response.json() if response.content else None
        except (json.JSONDecodeError, UnicodeDecodeError):
            body = None
        return FeedResponse(
            status=response.status_code,
            headers={name.lower(): value for name, value in response.headers.items()},
            body=body,
        )

    async def aclose(self) -> None:
        await self._client.aclose()


# --- K3 plug-in point ------------------------------------------------------------------------
#
# When #85 (qs_template.service_client) is merged, add here:
#
#     from qs_template.service_client import ServiceCallError, ServiceClient
#
#     class ServiceClientFeed:
#         """A FeedClient over K3's ServiceClient."""
#
#         def __init__(self, client: ServiceClient) -> None:
#             self._client = client
#
#         async def get(self, path, params=None) -> FeedResponse:
#             try:
#                 response = await self._client.get(path, params=params)
#             except ServiceCallError as exc:
#                 # upstream-error (502) carries the provider's 4xx/500 status and problem
#                 # body in exc.extra: return it as a FeedResponse so the adapter maps it;
#                 # upstream-down and circuit-open (503) raise FeedUnavailable (transient).
#                 ...
#             return FeedResponse(response.status_code, {lower-cased headers}, response.json())
#
#     def service_client_feed(base_url, settings) -> ServiceClientFeed:
#         return ServiceClientFeed(ServiceClient(base_url, caller=CALLER,
#                                  tokens=StaticServiceToken.from_settings(settings)))
#
# and make jobs.environment_factory build ServiceClientFeed instead of HttpxFeedClient.
