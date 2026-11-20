"""The :class:`~qs_trading.ports.market_environment.MarketEnvironment` adapters over Lane
B's HTTP feeds (task A17; contracts C1 and C2, ADR 01 and 08).

:class:`ReplayFeed` reads a historical replay from the market service::

    GET /api/market/environments/{id}                         the environment
    GET /api/market/environments/{id}/ticks?after_seq=&limit= a page of ticks

:class:`SimulationPathFeed` reads one path of a completed simulation run::

    GET /api/simulation/runs/{id}                             the run
    GET /api/simulation/runs/{id}/ticks?path=&after_seq=&limit=

Both read through a :class:`~qs_trading.adapters.feed_client.FeedClient`. A page is
``{"items": [tick, ...], "next_after_seq": n | null}`` with the header
``X-Source-Fingerprint``; ``limit`` is never above
:data:`~qs_trading.ports.market_environment.MAX_PAGE_SIZE` (2000).

**Ticks.** Each item is a ``market.tick.v1`` tick: decimals are strings (a JSON number is
refused), ``ts`` is ISO 8601 with a zone and is kept in UTC, unknown fields are ignored,
``env_type`` ``synthetic`` is the port's ``simulation``. Every page is checked: ``seq``
continues from ``after_seq`` without a gap (so across pages too), ticks are ordered by
``(session, symbol)`` (also against the last tick of the previous page), prices are above
zero with ``high >= low``, a tick's ``env_id``, ``env_type``, ``path_index`` and
``source_fingerprint`` match the environment and the page, a page holds at most ``limit``
items and ``next_after_seq`` is its last ``seq`` (or null on the last page). A page that
breaks these rules raises :class:`FeedContractViolation`.

**Activation.** :meth:`activate` reads the environment (or run) first: it must exist, a
replay must be ``active`` (activated in the market service, which froze its fingerprint),
a run must be ``completed`` and hold the path. The frozen fingerprint is the detail's
``source_fingerprint`` when the provider gives it (asked for in the review of the
contract, #80), otherwise the ``X-Source-Fingerprint`` of the first page (the contract as
it is in #80 today). The adapter never calls ``POST .../activate``: activating an
environment is a quant's decision in the market service, not a worker's.

**Fingerprint cache.** The engine reads :meth:`fingerprint` before committing every
session (:func:`~qs_trading.engine.runner.run_portfolio`), so a 252-session run would
otherwise make 252 requests. The adapter remembers the last fingerprint it was served
(by any page, or by a probe of one tick) and answers from memory for
``fingerprint_ttl_seconds`` (default 30 s, ``QS_TRADING_FINGERPRINT_CACHE_SECONDS``); after
that it probes the feed again (``after_seq=0&limit=1``). A page served under another
fingerprint replaces the cached value at once, so a change seen while paging is never
hidden by the cache. A change that lands mid-run is therefore seen within the interval
at worst, which bounds the sessions committed under the old data to those the engine runs
in that time; the engine still refuses to mix two fingerprints within one page load.

**Errors.** Permanent (listed in :data:`qs_trading.jobs.PERMANENT_ERRORS` through
:class:`PermanentFeedError`, or already there): 404 :class:`EnvironmentNotFound`; 401 and
403 :class:`FeedUnauthorized`; 409 or a non-active environment or a run that is not
completed :class:`EnvironmentNotActive`; 422 ``missing-adjusted-prices``
:class:`~qs_trading.ports.market_environment.MissingAdjustedPrices`; any other 4xx
:class:`FeedRefused`; 501 :class:`FeedNotImplemented` (the route is not built yet: a retry
in seconds cannot change that); a response that breaks the contract
:class:`FeedContractViolation`; a fingerprint other than the frozen one
:class:`~qs_trading.ports.market_environment.FingerprintChanged`. Transient (retried by
the job queue): 429 and every other 5xx, timeouts and connection errors, all
:class:`~qs_trading.adapters.feed_client.FeedUnavailable`.
"""

import re
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from itertools import pairwise
from typing import Any
from urllib.parse import quote

from qs_trading.adapters.feed_client import FeedClient, FeedResponse, FeedUnavailable
from qs_trading.ports.market_environment import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    EnvironmentRef,
    EnvType,
    FingerprintChanged,
    MarketEnvironmentError,
    MissingAdjustedPrices,
    Tick,
    TickPage,
)

__all__ = [
    "DEFAULT_FINGERPRINT_TTL_SECONDS",
    "FINGERPRINT_HEADER",
    "EnvironmentNotActive",
    "EnvironmentNotFound",
    "FeedContractViolation",
    "FeedNotImplemented",
    "FeedRefused",
    "FeedUnauthorized",
    "PermanentFeedError",
    "ReplayFeed",
    "SimulationPathFeed",
    "parse_tick",
]

FINGERPRINT_HEADER = "X-Source-Fingerprint"
DEFAULT_FINGERPRINT_TTL_SECONDS = 30.0

MISSING_ADJUSTED_PRICES = "missing-adjusted-prices"
"""The problem type's last part: ``urn:quantsim:problem:missing-adjusted-prices`` (asked for
in the #80 review; DL-005 writes it ``missing_adjusted_prices``, so both spellings match)."""

_DECIMAL = re.compile(r"^(0|[1-9][0-9]*)(\.[0-9]+)?$")
_ENV_TYPES: Mapping[str, EnvType] = {
    "replay": "replay",
    "historical_replay": "replay",
    "synthetic": "simulation",
    "simulation": "simulation",
}


class PermanentFeedError(MarketEnvironmentError):
    """The feed answered in a way a retry cannot change; the job fails for good."""


class EnvironmentNotFound(PermanentFeedError):
    """404: the environment or the run does not exist."""


class FeedUnauthorized(PermanentFeedError):
    """401 or 403: the provider refused the trading service's token."""


class EnvironmentNotActive(PermanentFeedError):
    """409, or a replay that is not activated, or a run that is not completed."""


class FeedNotImplemented(PermanentFeedError):
    """501: the provider has not built the route yet."""


class FeedRefused(PermanentFeedError):
    """Any other 4xx (a bad parameter, or an environment that cannot be replayed)."""


class FeedContractViolation(PermanentFeedError):
    """The answer breaks the contract (C1, C2): a gap in ``seq``, a malformed tick, a
    page larger than asked for, a missing fingerprint ..."""


# --- answers --------------------------------------------------------------------------------


def _problem(response: FeedResponse) -> tuple[str, str]:
    """The problem ``type`` and a readable detail of an error answer."""
    body = response.body if isinstance(response.body, Mapping) else {}
    kind = str(body.get("type") or "")
    detail = body.get("detail") or body.get("title") or ""
    text = f"HTTP {response.status}"
    if kind:
        text += f" {kind}"
    if detail:
        text += f": {detail}"
    return kind, text


def _check(response: FeedResponse, what: str) -> None:
    """Raises the error a non-200 answer means (see the module docstring)."""
    status = response.status
    if status == 200:
        return
    kind, text = _problem(response)
    message = f"{what}: {text}"
    if status in (401, 403):
        raise FeedUnauthorized(
            f"{what}: the provider refused the trading service's token ({text}); "
            "check QS_SERVICE_TOKEN"
        )
    if status == 404:
        raise EnvironmentNotFound(message)
    if status == 409:
        raise EnvironmentNotActive(message)
    if status == 422 and kind.rsplit(":", 1)[-1].replace("_", "-") == MISSING_ADJUSTED_PRICES:
        raise MissingAdjustedPrices(message)
    if status == 501:
        raise FeedNotImplemented(message)
    if status == 429 or status >= 500:
        raise FeedUnavailable(message)
    if 400 <= status < 500:
        raise FeedRefused(message)
    raise FeedContractViolation(f"{what}: unexpected HTTP {status}")


# --- ticks ----------------------------------------------------------------------------------


def _decimal(item: Mapping[str, Any], name: str, seq: object) -> Decimal:
    value = item.get(name)
    if not isinstance(value, str) or not _DECIMAL.match(value):
        raise FeedContractViolation(f"tick {seq}: {name} must be a decimal string, got {value!r}")
    return Decimal(value)


def _whole(item: Mapping[str, Any], name: str, seq: object, minimum: int) -> int:
    value = item.get(name)
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise FeedContractViolation(f"tick {seq}: {name} must be a whole number >= {minimum}")
    return value


def parse_tick(item: Any, ref: EnvironmentRef, fingerprint: str) -> Tick:
    """One ``market.tick.v1`` item as a port :class:`Tick`, checked against the
    environment it was served for and the page's fingerprint."""
    if not isinstance(item, Mapping):
        raise FeedContractViolation(f"a tick must be an object, got {item!r}")
    seq = item.get("seq")
    env_id = item.get("env_id")
    if env_id is not None and str(env_id).lower() != ref.env_id.lower():
        raise FeedContractViolation(f"tick {seq} belongs to {env_id}, not {ref.env_id}")
    env_type = item.get("env_type")
    if env_type is not None and _ENV_TYPES.get(str(env_type)) != ref.env_type:
        raise FeedContractViolation(f"tick {seq} is {env_type!r}, not a {ref.env_type} tick")
    path_index = item.get("path_index")
    if ref.env_type == "simulation":
        if path_index is not None and path_index != ref.path_index:
            raise FeedContractViolation(f"tick {seq} is on path {path_index}, not {ref.path_index}")
    elif path_index is not None:
        raise FeedContractViolation(f"replay tick {seq} carries path_index {path_index}")
    carried = item.get("source_fingerprint")
    if carried is not None and carried != fingerprint:
        raise FeedContractViolation(
            f"tick {seq} carries source_fingerprint {carried!r}, but the page was served "
            f"under {fingerprint!r}"
        )
    symbol = item.get("symbol")
    if not isinstance(symbol, str) or not symbol:
        raise FeedContractViolation(f"tick {seq}: symbol is missing")
    raw_ts = item.get("ts")
    try:
        ts = datetime.fromisoformat(raw_ts) if isinstance(raw_ts, str) else None
    except ValueError:
        ts = None
    if ts is None or ts.utcoffset() is None:
        raise FeedContractViolation(f"tick {seq}: ts must be an ISO 8601 time with a zone")
    tick = Tick(
        seq=_whole(item, "seq", seq, 1),
        session=_whole(item, "session", seq, 0),
        symbol=symbol,
        ts=ts.astimezone(UTC),
        open=_decimal(item, "open", seq),
        high=_decimal(item, "high", seq),
        low=_decimal(item, "low", seq),
        close=_decimal(item, "close", seq),
        volume=_decimal(item, "volume", seq),
    )
    if min(tick.open, tick.high, tick.low, tick.close) <= 0:
        raise FeedContractViolation(f"tick {seq}: prices must be above zero")
    if tick.high < tick.low:
        raise FeedContractViolation(f"tick {seq}: high is below low")
    return tick


def _page_fingerprint(response: FeedResponse, items: Sequence[Any], what: str) -> str:
    """The page's fingerprint: the header, or (without one) the value every tick carries."""
    header = response.header(FINGERPRINT_HEADER)
    if header:
        return header
    carried = {item.get("source_fingerprint") for item in items if isinstance(item, Mapping)}
    if len(carried) == 1 and (value := carried.pop()):
        return str(value)
    raise FeedContractViolation(f"{what}: the page has no {FINGERPRINT_HEADER} header")


@dataclass(frozen=True, slots=True)
class _Cached:
    fingerprint: str
    at: float


class _HttpFeed:
    """What both feeds share: paging, checks, activation and the fingerprint cache."""

    def __init__(
        self,
        client: FeedClient,
        ref: EnvironmentRef,
        *,
        fingerprint_ttl_seconds: float = DEFAULT_FINGERPRINT_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if fingerprint_ttl_seconds < 0:
            raise ValueError("fingerprint_ttl_seconds cannot be negative")
        self._client = client
        self._ref = ref
        self._ttl = fingerprint_ttl_seconds
        self._clock = clock
        self._frozen: str | None = None
        self._cached: _Cached | None = None
        self._tail: Tick | None = None

    # the two feeds differ only in these
    def _detail_path(self) -> str:
        raise NotImplementedError

    def _ticks_path(self) -> str:
        raise NotImplementedError

    def _ticks_params(self) -> dict[str, int | str]:
        return {}

    def _check_detail(self, detail: Mapping[str, Any]) -> None:
        raise NotImplementedError

    @property
    def ref(self) -> EnvironmentRef:
        return self._ref

    @property
    def frozen_fingerprint(self) -> str | None:
        """The fingerprint frozen by :meth:`activate`; ``None`` before activation."""
        return self._frozen

    def _what(self) -> str:
        if self._ref.env_type == "simulation":
            return f"simulation run {self._ref.env_id} path {self._ref.path_index}"
        return f"replay environment {self._ref.env_id}"

    async def _read(self, after_seq: int, limit: int) -> TickPage:
        """One page, checked, with no comparison to the frozen fingerprint."""
        if after_seq < 0:
            raise ValueError(f"after_seq cannot be negative, got {after_seq}")
        if not 1 <= limit <= MAX_PAGE_SIZE:
            raise ValueError(f"limit must be between 1 and {MAX_PAGE_SIZE}, got {limit}")
        what = self._what()
        params: dict[str, int | str] = {
            **self._ticks_params(),
            "after_seq": after_seq,
            "limit": limit,
        }
        response = await self._client.get(self._ticks_path(), params)
        _check(response, what)
        body = response.body
        if not isinstance(body, Mapping) or not isinstance(body.get("items"), list):
            raise FeedContractViolation(f"{what}: a page must be {{items, next_after_seq}}")
        raw: list[Any] = body["items"]
        next_after_seq = body.get("next_after_seq")
        if next_after_seq is not None and (
            isinstance(next_after_seq, bool) or not isinstance(next_after_seq, int)
        ):
            raise FeedContractViolation(f"{what}: next_after_seq must be a whole number or null")
        if len(raw) > limit:
            raise FeedContractViolation(f"{what}: asked for {limit} ticks, got {len(raw)}")
        fingerprint = _page_fingerprint(response, raw, what)
        items = [parse_tick(item, self._ref, fingerprint) for item in raw]
        for expected, tick in enumerate(items, start=after_seq + 1):
            if tick.seq != expected:
                raise FeedContractViolation(
                    f"{what}: seq must run without gaps: expected {expected}, got {tick.seq}"
                )
        for before, after in pairwise(items):
            if (before.session, before.symbol) >= (after.session, after.symbol):
                raise FeedContractViolation(
                    f"{what}: ticks must be ordered by (session, symbol) at seq {after.seq}"
                )
        if next_after_seq is not None and (not items or next_after_seq != items[-1].seq):
            raise FeedContractViolation(
                f"{what}: next_after_seq {next_after_seq} is not the last seq of the page"
            )
        self._cached = _Cached(fingerprint, self._clock())
        return TickPage(items=items, next_after_seq=next_after_seq, fingerprint=fingerprint)

    async def _detail(self) -> Mapping[str, Any]:
        what = self._what()
        response = await self._client.get(self._detail_path())
        _check(response, what)
        if not isinstance(response.body, Mapping):
            raise FeedContractViolation(f"{what}: the detail must be a JSON object")
        detail: Mapping[str, Any] = response.body
        self._check_detail(detail)
        return detail

    async def activate(self) -> str:
        """Checks the environment can be read and freezes its fingerprint: the detail's
        ``source_fingerprint`` when given, else the first page's header."""
        detail = await self._detail()
        declared = detail.get("source_fingerprint")
        if declared is not None and (not isinstance(declared, str) or not declared):
            raise FeedContractViolation(
                f"{self._what()}: source_fingerprint must be a non-empty string"
            )
        self._frozen = declared or (await self._read(0, 1)).fingerprint
        self._tail = None
        return self._frozen

    async def fingerprint(self) -> str:
        """The fingerprint the feed serves now; answered from memory for
        ``fingerprint_ttl_seconds`` after the last page or probe."""
        cached = self._cached
        if cached is not None and self._clock() - cached.at < self._ttl:
            return cached.fingerprint
        return (await self._read(0, 1)).fingerprint

    async def ticks(self, after_seq: int = 0, limit: int = DEFAULT_PAGE_SIZE) -> TickPage:
        page = await self._read(after_seq, limit)
        if self._frozen is not None and page.fingerprint != self._frozen:
            raise FingerprintChanged(self._frozen, page.fingerprint)
        tail = self._tail
        if page.items and tail is not None and tail.seq == after_seq:
            first = page.items[0]
            if (tail.session, tail.symbol) >= (first.session, first.symbol):
                raise FeedContractViolation(
                    f"{self._what()}: ticks must be ordered by (session, symbol) at seq {first.seq}"
                )
        if page.items:
            self._tail = page.items[-1]
        return page


class ReplayFeed(_HttpFeed):
    """A historical replay served by the market service."""

    PREFIX = "/api/market/environments"

    def __init__(
        self,
        client: FeedClient,
        env_id: str,
        *,
        fingerprint_ttl_seconds: float = DEFAULT_FINGERPRINT_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__(
            client,
            EnvironmentRef("replay", env_id),
            fingerprint_ttl_seconds=fingerprint_ttl_seconds,
            clock=clock,
        )

    def _detail_path(self) -> str:
        return f"{self.PREFIX}/{quote(self._ref.env_id, safe='')}"

    def _ticks_path(self) -> str:
        return f"{self._detail_path()}/ticks"

    def _check_detail(self, detail: Mapping[str, Any]) -> None:
        kind = detail.get("type")
        if kind is not None and _ENV_TYPES.get(str(kind)) != "replay":
            raise FeedRefused(f"{self._what()} is {kind!r}, not a historical replay")
        status = detail.get("status")
        if status is not None and status != "active":
            raise EnvironmentNotActive(
                f"{self._what()} is {status!r}; it must be activated in the market service "
                "before a portfolio runs on it"
            )


class SimulationPathFeed(_HttpFeed):
    """One path of a completed simulation run, served by the simulation service."""

    PREFIX = "/api/simulation/runs"

    def __init__(
        self,
        client: FeedClient,
        run_id: str,
        path_index: int,
        *,
        fingerprint_ttl_seconds: float = DEFAULT_FINGERPRINT_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if isinstance(path_index, bool) or not isinstance(path_index, int) or path_index < 0:
            raise ValueError(f"path_index must be a whole number >= 0, got {path_index!r}")
        super().__init__(
            client,
            EnvironmentRef("simulation", run_id, path_index),
            fingerprint_ttl_seconds=fingerprint_ttl_seconds,
            clock=clock,
        )
        self.median_path_index: int | None = None

    def _detail_path(self) -> str:
        return f"{self.PREFIX}/{quote(self._ref.env_id, safe='')}"

    def _ticks_path(self) -> str:
        return f"{self._detail_path()}/ticks"

    def _ticks_params(self) -> dict[str, int | str]:
        # always explicit: the route's default path (0) is never relied on
        assert self._ref.path_index is not None  # checked in __init__
        return {"path": self._ref.path_index}

    def _check_detail(self, detail: Mapping[str, Any]) -> None:
        status = detail.get("status")
        if status is not None and status != "completed":
            raise EnvironmentNotActive(f"{self._what()}: the run is {status!r}, not completed")
        n_paths = detail.get("n_paths")
        path_index = self._ref.path_index
        if isinstance(n_paths, int) and path_index is not None and path_index >= n_paths:
            raise FeedRefused(f"{self._what()}: the run has {n_paths} paths")
        median = detail.get("median_path_index")
        if isinstance(median, int) and not isinstance(median, bool):
            self.median_path_index = median
