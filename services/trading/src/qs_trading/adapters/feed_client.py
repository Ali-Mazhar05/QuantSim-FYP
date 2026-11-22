"""The small HTTP client the market feed adapters (task A17) read through.

The adapters in :mod:`qs_trading.adapters.http_environment` depend only on
:class:`FeedClient`: one ``GET`` that returns the status, the headers and the decoded JSON
body of an answer the provider gave. Deciding what a status means (a permanent or a
transient failure) is the adapter's job, so a test can serve the contract from a script
and the transport underneath can change without touching the adapters.

:class:`ServiceClientFeed` is the implementation: it reads through the platform kit's
:class:`~qs_template.service_client.ServiceClient` (K3, ADR 09), which sends the service
token from its :class:`~qs_template.service_client.TokenProvider` and
``X-Calling-Service: trading``, applies the per-request timeout, retries a timeout, a
connection error, 429, 502, 503 and 504 with backoff, and opens its circuit after
repeated failures. Its :class:`~qs_template.service_client.ServiceCallError` is mapped
back to the answer or the error the adapters already understand:

==========================================  ==============================================
``ServiceCallError``                        what the adapter sees
==========================================  ==============================================
``upstream-error`` (the provider answered   the provider's own status and problem body, as
4xx or 500)                                 a :class:`FeedResponse`; the adapter maps it
                                            (404, 422 ``missing-adjusted-prices`` ... are
                                            permanent, 500 is transient)
``upstream-down`` (retries exhausted)       :class:`FeedUnavailable` (transient)
``circuit-open`` (call not sent)            :class:`FeedUnavailable` (transient)
==========================================  ==============================================

The token provider is injected (see :func:`qs_trading.jobs.environment_factory`): today the
DEV ``StaticServiceToken``, later the Platform service's real tokens, changed in one place.
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from qs_template.service_client import ServiceCallError, ServiceClient, TokenProvider
from qs_trading.ports.market_environment import MarketEnvironmentError

__all__ = [
    "CALLER",
    "FeedClient",
    "FeedResponse",
    "FeedUnavailable",
    "ServiceClientFeed",
    "TokenProvider",
    "service_client_feed",
]

CALLER = "trading"
"""Sent as ``X-Calling-Service`` by the ``ServiceClient``."""

UPSTREAM_ERROR = "urn:quantsim:problem:upstream-error"


class FeedUnavailable(MarketEnvironmentError):
    """The feed could not be read now (connection error, timeout, 429 or 5xx, or the
    circuit is open); transient, so the job is retried."""


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
        """``GET path``; answers every status the provider gave, raises
        :class:`FeedUnavailable` when no usable answer came."""
        ...


def _json(response: httpx.Response) -> Any:
    if not response.content:
        return None
    try:
        return response.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


class ServiceClientFeed:
    """A :class:`FeedClient` over K3's :class:`ServiceClient` (one per provider, shared by
    every run of the worker, so its circuit breaker sees all of them)."""

    def __init__(self, client: ServiceClient) -> None:
        self._client = client

    @property
    def service_client(self) -> ServiceClient:
        return self._client

    async def get(self, path: str, params: Mapping[str, int | str] | None = None) -> FeedResponse:
        try:
            response = await self._client.get(path, params=dict(params or {}))
        except ServiceCallError as exc:
            status = exc.extra.get("upstream_status")
            if exc.type == UPSTREAM_ERROR and isinstance(status, int):
                body = exc.extra.get("upstream_body")
                return FeedResponse(status, {}, body if isinstance(body, Mapping) else None)
            raise FeedUnavailable(f"{path}: {exc.detail}") from None
        return FeedResponse(
            status=response.status_code,
            headers={name.lower(): value for name, value in response.headers.items()},
            body=_json(response),
        )

    async def aclose(self) -> None:
        await self._client.close()


def service_client_feed(
    base_url: str,
    tokens: TokenProvider,
    *,
    timeout_seconds: float = 10.0,
    **options: Any,
) -> ServiceClientFeed:
    """A :class:`ServiceClientFeed` on ``base_url``; ``options`` go to the
    :class:`ServiceClient` (``retries``, ``breaker``, ``transport``, ``sleep`` ...)."""
    return ServiceClientFeed(
        ServiceClient(
            base_url,
            caller=CALLER,
            tokens=tokens,
            timeout_seconds=timeout_seconds,
            **options,
        )
    )
