"""A :class:`~qs_trading.ports.market_environment.MarketEnvironment` over a recorded
fixture file (task A14), so the engine runs and is tested with no other service up.

**File format.** One JSON document, the shape of Lane B's contract fixtures
(``contracts/fixtures/replay_ticks_2020.json``)::

    {"meta": {...},                          # optional, ignored
     "environment": {"id": "<env id>",
                     "type": "historical_replay" | "replay" | "synthetic" | "simulation",
                     "path_index": 0,         # simulations only (else read from the ticks)
                     ...},                    # other keys ignored
     "items": [tick, ...]}                    # market.tick.v1 ticks

Each tick needs ``seq``, ``session``, ``symbol``, ``ts`` (ISO 8601 with a zone) and
``open``, ``high``, ``low``, ``close``, ``volume`` as decimal strings (an integer is
accepted, a JSON float is refused as in the contract); other fields (``env_id``,
``instrument_id``, ``session_date``, ``scenario`` ...) are ignored. The file is checked on
every read: ``seq`` runs 1, 2, 3 without gaps, ticks are strictly ordered by
``(session, symbol)``, prices are above zero with ``high >= low``, and volume is not
negative (the contract's own rules).

**Fingerprint.** ``sha256:`` and the hex SHA-256 of the file's bytes, so any edit to the
file changes it. :meth:`FileEnvironment.activate` freezes it; from then on a read that
finds other bytes raises
:class:`~qs_trading.ports.market_environment.FingerprintChanged`.
"""

import asyncio
import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from decimal import Decimal, InvalidOperation
from itertools import pairwise
from pathlib import Path
from typing import Any

from qs_trading.ports.market_environment import (
    MAX_PAGE_SIZE,
    EnvironmentRef,
    EnvType,
    FingerprintChanged,
    MarketEnvironmentError,
    Tick,
    TickPage,
)

__all__ = ["FileEnvironment", "file_environments", "fingerprint_of"]

_ENV_TYPES: Mapping[str, EnvType] = {
    "historical_replay": "replay",
    "replay": "replay",
    "synthetic": "simulation",
    "simulation": "simulation",
}


def fingerprint_of(content: bytes) -> str:
    """The source fingerprint of a fixture file's bytes."""
    return "sha256:" + hashlib.sha256(content).hexdigest()


class FixtureError(MarketEnvironmentError):
    """The fixture file is missing, unreadable or breaks the tick rules."""


def _decimal(item: Mapping[str, Any], name: str, seq: object) -> Decimal:
    value = item.get(name)
    if isinstance(value, bool) or not isinstance(value, str | int):
        raise FixtureError(f"tick {seq}: {name} must be a decimal string, got {value!r}")
    try:
        result = Decimal(value)
    except InvalidOperation:
        raise FixtureError(f"tick {seq}: {name} is not a number: {value!r}") from None
    if not result.is_finite():
        raise FixtureError(f"tick {seq}: {name} is not finite")
    return result


def _whole(item: Mapping[str, Any], name: str, seq: object, minimum: int) -> int:
    value = item.get(name)
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise FixtureError(f"tick {seq}: {name} must be a whole number >= {minimum}")
    return value


def _tick(item: Any) -> Tick:
    if not isinstance(item, Mapping):
        raise FixtureError(f"a tick must be an object, got {item!r}")
    seq = item.get("seq")
    symbol = item.get("symbol")
    if not isinstance(symbol, str) or not symbol:
        raise FixtureError(f"tick {seq}: symbol is missing")
    raw_ts = item.get("ts")
    try:
        ts = datetime.fromisoformat(raw_ts) if isinstance(raw_ts, str) else None
    except ValueError:
        ts = None
    if ts is None or ts.utcoffset() is None:
        raise FixtureError(f"tick {seq}: ts must be an ISO 8601 time with a zone")
    tick = Tick(
        seq=_whole(item, "seq", seq, 1),
        session=_whole(item, "session", seq, 0),
        symbol=symbol,
        ts=ts,
        open=_decimal(item, "open", seq),
        high=_decimal(item, "high", seq),
        low=_decimal(item, "low", seq),
        close=_decimal(item, "close", seq),
        volume=_decimal(item, "volume", seq),
    )
    if min(tick.open, tick.high, tick.low, tick.close) <= 0:
        raise FixtureError(f"tick {seq}: prices must be above zero")
    if tick.high < tick.low:
        raise FixtureError(f"tick {seq}: high is below low")
    if tick.volume < 0:
        raise FixtureError(f"tick {seq}: volume cannot be negative")
    return tick


def _parse(content: bytes) -> tuple[EnvironmentRef, tuple[Tick, ...]]:
    try:
        document = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FixtureError(f"the fixture is not valid JSON: {exc}") from None
    if not isinstance(document, Mapping):
        raise FixtureError("the fixture must be a JSON object")
    environment = document.get("environment")
    items = document.get("items")
    if not isinstance(environment, Mapping) or not isinstance(items, list):
        raise FixtureError("the fixture needs an 'environment' object and an 'items' list")
    env_type = _ENV_TYPES.get(str(environment.get("type")))
    env_id = environment.get("id")
    if env_type is None or not isinstance(env_id, str) or not env_id:
        raise FixtureError("the environment needs an id and a known type")
    ticks = tuple(_tick(item) for item in items)
    for expected, tick in enumerate(ticks, start=1):
        if tick.seq != expected:
            raise FixtureError(f"seq must run 1, 2, 3 without gaps: expected {expected}")
    for before, after in pairwise(ticks):
        if (before.session, before.symbol) >= (after.session, after.symbol):
            raise FixtureError(f"ticks must be ordered by (session, symbol) at seq {after.seq}")
    path_index: int | None = None
    if env_type == "simulation":
        raw = environment.get("path_index")
        if raw is None and items:
            raw = items[0].get("path_index")
        if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
            raise FixtureError("a simulation fixture needs a path_index")
        path_index = raw
    return EnvironmentRef(env_type, env_id, path_index), ticks


class FileEnvironment:
    """Serves the ticks of one fixture file. A change to the file is noticed: before every
    call its size and modification time are checked, and it is read, hashed and parsed
    again only when either changed (the engine asks for the fingerprint once per session,
    and re-hashing a large fixture each time dominated a run's time)."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._frozen: str | None = None
        self._stat_key: tuple[int, int] | None = None
        self._current: tuple[str, tuple[EnvironmentRef, tuple[Tick, ...]]] | None = None
        self._ref = self._snapshot_now()[1][0]

    @property
    def ref(self) -> EnvironmentRef:
        return self._ref

    @property
    def frozen_fingerprint(self) -> str | None:
        """The fingerprint frozen by :meth:`activate`; ``None`` before activation."""
        return self._frozen

    def _snapshot_now(self) -> tuple[str, tuple[EnvironmentRef, tuple[Tick, ...]]]:
        """The file's fingerprint and parsed content, read again only when its size or
        modification time changed since the last read."""
        try:
            stat = self.path.stat()
            key = (stat.st_mtime_ns, stat.st_size)
            if self._current is not None and key == self._stat_key:
                return self._current
            content = self.path.read_bytes()
        except OSError as exc:
            raise FixtureError(f"cannot read the fixture {self.path}: {exc}") from None
        fingerprint = fingerprint_of(content)
        if self._current is None or self._current[0] != fingerprint:
            self._current = (fingerprint, _parse(content))
        self._stat_key = key
        return self._current

    async def _snapshot(self) -> tuple[str, tuple[EnvironmentRef, tuple[Tick, ...]]]:
        return await asyncio.to_thread(self._snapshot_now)

    async def activate(self) -> str:
        """Freezes and returns the fingerprint of the file as it is now."""
        self._frozen = (await self._snapshot())[0]
        return self._frozen

    async def fingerprint(self) -> str:
        return (await self._snapshot())[0]

    async def ticks(self, after_seq: int = 0, limit: int = 1000) -> TickPage:
        if after_seq < 0:
            raise ValueError(f"after_seq cannot be negative, got {after_seq}")
        if not 1 <= limit <= MAX_PAGE_SIZE:
            raise ValueError(f"limit must be between 1 and {MAX_PAGE_SIZE}, got {limit}")
        fingerprint, (ref, ticks) = await self._snapshot()
        if self._frozen is not None and fingerprint != self._frozen:
            raise FingerprintChanged(self._frozen, fingerprint)
        if ref != self._ref:
            raise FixtureError(f"the fixture now describes {ref}, not {self._ref}")
        # seq is gap-free from 1, so seq n is at index n - 1
        items: Sequence[Tick] = ticks[after_seq : after_seq + limit]
        more = after_seq + len(items) < len(ticks)
        return TickPage(
            items=items,
            next_after_seq=items[-1].seq if items and more else None,
            fingerprint=fingerprint,
        )


def file_environments(directory: Path | str) -> Callable[[EnvironmentRef], FileEnvironment]:
    """An environment factory over a directory of fixtures: ``<env_id>.json`` for a
    replay, ``<env_id>.path-<path_index>.json`` for one simulation path."""
    root = Path(directory)

    def open_environment(ref: EnvironmentRef) -> FileEnvironment:
        name = f"{ref.env_id}.json"
        if ref.path_index is not None:
            name = f"{ref.env_id}.path-{ref.path_index}.json"
        environment = FileEnvironment(root / name)
        if environment.ref != ref:
            raise FixtureError(f"{root / name} describes {environment.ref}, not {ref}")
        return environment

    return open_environment
