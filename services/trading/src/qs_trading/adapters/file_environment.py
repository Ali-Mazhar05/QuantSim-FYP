"""A :class:`~qs_trading.ports.market_environment.MarketEnvironment` over a recorded
fixture file (task A14), so the engine runs and is tested with no other service up.

**File formats.** One JSON document in either shape of Lane B's contract fixtures (C3).

A replay, or one path of a simulation (``contracts/fixtures/replay_ticks_2020.json``)::

    {"meta": {...},                          # optional, ignored
     "environment": {"id": "<env id>",
                     "type": "historical_replay" | "replay" | "synthetic" | "simulation",
                     "path_index": 0,         # simulations only (else read from the ticks)
                     "source_fingerprint": "xxh3:...",   # optional
                     ...},                    # other keys ignored
     "items": [tick, ...],                    # market.tick.v1 ticks
     "next_after_seq": null}                  # optional, ignored

A synthetic run with several paths (``contracts/fixtures/synthetic_ticks.json``); it is
opened with ``FileEnvironment(path, path_index=n)`` and serves that path::

    {"meta": {...},
     "run": {"id": "<run id>", "source_fingerprint": "xxh3:...",   # fingerprint optional
             "median_path_index": 2, ...},
     "paths": [{"path_index": 0, "items": [tick, ...], "next_after_seq": null}, ...]}

Each tick needs ``seq``, ``session``, ``symbol``, ``ts`` (ISO 8601 with a zone) and
``open``, ``high``, ``low``, ``close``, ``volume`` as decimal strings (an integer is
accepted, a JSON float is refused as in the contract); other fields (``env_id``,
``instrument_id``, ``session_date``, ``scenario`` ...) are ignored, except that a tick's
``source_fingerprint`` must equal the declared one and a tick's ``path_index`` the path's.
The file is checked on every read: ``seq`` runs 1, 2, 3 without gaps, ticks are strictly
ordered by ``(session, symbol)``, prices are above zero with ``high >= low``, and volume is
not negative (the contract's own rules).

**Fingerprint.** When the fixture declares a source fingerprint (``environment`` or
``run``.``source_fingerprint``, the ``xxh3:`` value the provider computed, ADR 08), that
value is the environment's fingerprint, so a run over the file and a run over the HTTP
feed of the same ticks record the same one. Otherwise it is ``sha256:`` and the hex
SHA-256 of the file's bytes (the DEV demo environments). :meth:`FileEnvironment.activate`
freezes it; from then on a read that finds another fingerprint raises
:class:`~qs_trading.ports.market_environment.FingerprintChanged`. Changes to the file are
always detected by its bytes: if they change after activation while the declared value
stays the same, :meth:`~FileEnvironment.ticks` and :meth:`~FileEnvironment.fingerprint`
raise :class:`FixtureChanged` (a ``FingerprintChanged`` whose ``expected`` and ``actual``
are both the declared value), with the message ``the fixture <path> changed after
activation: it still declares <fingerprint>, but its bytes went from sha256:<a> to
sha256:<b>``.
"""

import asyncio
import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from itertools import pairwise
from pathlib import Path
from typing import Any

from qs_trading.ports.market_environment import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    EnvironmentRef,
    EnvType,
    FingerprintChanged,
    MarketEnvironmentError,
    Tick,
    TickPage,
)

__all__ = [
    "FileEnvironment",
    "FixtureChanged",
    "FixtureError",
    "file_environments",
    "fingerprint_of",
]

_ENV_TYPES: Mapping[str, EnvType] = {
    "historical_replay": "replay",
    "replay": "replay",
    "synthetic": "simulation",
    "simulation": "simulation",
}


def fingerprint_of(content: bytes) -> str:
    """The byte fingerprint of a fixture file (used when it declares none)."""
    return "sha256:" + hashlib.sha256(content).hexdigest()


class FixtureError(MarketEnvironmentError):
    """The fixture file is missing, unreadable or breaks the tick rules."""


class FixtureChanged(FingerprintChanged):
    """The fixture's bytes changed after activation although it declares the same source
    fingerprint; ``expected`` and ``actual`` are both that declared value."""

    def __init__(self, path: Path, declared: str, bytes_then: str, bytes_now: str) -> None:
        super().__init__(declared, declared)
        self.args = (
            f"the fixture {path} changed after activation: it still declares {declared},"
            f" but its bytes went from {bytes_then} to {bytes_now}",
        )


@dataclass(frozen=True, slots=True)
class _Fixture:
    """One parsed fixture: what it serves and the fingerprint it declares, if any."""

    ref: EnvironmentRef
    ticks: tuple[Tick, ...]
    declared: str | None
    median_path_index: int | None


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


def _index(value: Any) -> int | None:
    """A path index read from the file, or ``None`` when it is not a whole number >= 0."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
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


def _ticks(items: list[Any], declared: str | None, path_index: int | None) -> tuple[Tick, ...]:
    """Parses and checks the ticks of one environment or path."""
    ticks = tuple(_tick(item) for item in items)
    for item, tick in zip(items, ticks, strict=True):
        carried = item.get("source_fingerprint")
        if declared is not None and carried is not None and carried != declared:
            raise FixtureError(
                f"tick {tick.seq} carries source_fingerprint {carried!r},"
                f" but the fixture declares {declared!r}"
            )
        if path_index is not None and item.get("path_index", path_index) != path_index:
            raise FixtureError(f"tick {tick.seq} is not on path {path_index}")
    for expected, tick in enumerate(ticks, start=1):
        if tick.seq != expected:
            raise FixtureError(f"seq must run 1, 2, 3 without gaps: expected {expected}")
    for before, after in pairwise(ticks):
        if (before.session, before.symbol) >= (after.session, after.symbol):
            raise FixtureError(f"ticks must be ordered by (session, symbol) at seq {after.seq}")
    return ticks


def _declared(block: Mapping[str, Any]) -> str | None:
    value = block.get("source_fingerprint")
    if value is not None and (not isinstance(value, str) or not value):
        raise FixtureError(f"source_fingerprint must be a non-empty string, got {value!r}")
    return value


def _parse_environment(document: Mapping[str, Any], path_index: int | None) -> _Fixture:
    """The ``{environment, items}`` shape: a replay or one simulation path."""
    environment = document.get("environment")
    items = document.get("items")
    if not isinstance(environment, Mapping) or not isinstance(items, list):
        raise FixtureError("the fixture needs an 'environment' object and an 'items' list")
    env_type = _ENV_TYPES.get(str(environment.get("type")))
    env_id = environment.get("id")
    if env_type is None or not isinstance(env_id, str) or not env_id:
        raise FixtureError("the environment needs an id and a known type")
    declared = _declared(environment)
    if env_type == "replay":
        if path_index is not None:
            raise FixtureError("a replay fixture has no paths; open it without a path_index")
        return _Fixture(
            EnvironmentRef("replay", env_id), _ticks(items, declared, None), declared, None
        )
    raw = environment.get("path_index")
    if raw is None and items and isinstance(items[0], Mapping):
        raw = items[0].get("path_index")
    found = _index(raw)
    if found is None:
        raise FixtureError("a simulation fixture needs a path_index")
    if path_index is not None and path_index != found:
        raise FixtureError(f"the fixture holds path {found}, not path {path_index}")
    ticks = _ticks(items, declared, found)
    return _Fixture(EnvironmentRef("simulation", env_id, found), ticks, declared, None)


def _parse_run(document: Mapping[str, Any], path_index: int | None) -> _Fixture:
    """The ``{run, paths}`` shape: a synthetic run, of which one path is served."""
    run = document.get("run")
    paths = document.get("paths")
    if not isinstance(run, Mapping) or not isinstance(paths, list):
        raise FixtureError("a run fixture needs a 'run' object and a 'paths' list")
    run_id = run.get("id")
    if not isinstance(run_id, str) or not run_id:
        raise FixtureError("the run needs an id")
    if path_index is None:
        raise FixtureError("a synthetic run fixture holds several paths; pass a path_index")
    median = run.get("median_path_index")
    if median is not None and _index(median) is None:
        raise FixtureError(f"median_path_index must be a whole number >= 0, got {median!r}")
    declared = _declared(run)
    chosen = [p for p in paths if isinstance(p, Mapping) and p.get("path_index") == path_index]
    if len(chosen) != 1:
        raise FixtureError(f"the run fixture needs exactly one path {path_index}")
    items = chosen[0].get("items")
    if not isinstance(items, list):
        raise FixtureError(f"path {path_index} needs an 'items' list")
    ticks = _ticks(items, declared, path_index)
    return _Fixture(EnvironmentRef("simulation", run_id, path_index), ticks, declared, median)


def _parse(content: bytes, path_index: int | None) -> _Fixture:
    try:
        document = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FixtureError(f"the fixture is not valid JSON: {exc}") from None
    if not isinstance(document, Mapping):
        raise FixtureError("the fixture must be a JSON object")
    if "run" in document or "paths" in document:
        return _parse_run(document, path_index)
    return _parse_environment(document, path_index)


class FileEnvironment:
    """Serves the ticks of one fixture file (of one path of it, for a synthetic run
    fixture, chosen by ``path_index``). A change to the file is noticed: before every call
    its size and modification time are checked, and it is read, hashed and parsed again
    only when either changed (the engine asks for the fingerprint once per session, and
    re-hashing a large fixture each time dominated a run's time)."""

    def __init__(self, path: Path | str, path_index: int | None = None) -> None:
        if path_index is not None and _index(path_index) is None:
            raise ValueError(f"path_index must be a whole number >= 0, got {path_index!r}")
        self.path = Path(path)
        self.path_index = path_index
        self._frozen: str | None = None
        self._frozen_bytes: str | None = None
        self._stat_key: tuple[int, int] | None = None
        self._current: tuple[str, _Fixture] | None = None
        fixture = self._snapshot_now()[1]
        self._ref = fixture.ref
        self._median_path_index = fixture.median_path_index

    @property
    def ref(self) -> EnvironmentRef:
        return self._ref

    @property
    def frozen_fingerprint(self) -> str | None:
        """The fingerprint frozen by :meth:`activate`; ``None`` before activation."""
        return self._frozen

    @property
    def median_path_index(self) -> int | None:
        """The run's median path (``run.median_path_index``) for a synthetic run fixture;
        ``None`` for other fixtures."""
        return self._median_path_index

    def _snapshot_now(self) -> tuple[str, _Fixture]:
        """The file's byte fingerprint and parsed content, read again only when its size or
        modification time changed since the last read."""
        try:
            stat = self.path.stat()
            key = (stat.st_mtime_ns, stat.st_size)
            if self._current is not None and key == self._stat_key:
                return self._current
            content = self.path.read_bytes()
        except OSError as exc:
            raise FixtureError(f"cannot read the fixture {self.path}: {exc}") from None
        byte_fingerprint = fingerprint_of(content)
        if self._current is None or self._current[0] != byte_fingerprint:
            self._current = (byte_fingerprint, _parse(content, self.path_index))
        self._stat_key = key
        return self._current

    async def _snapshot(self) -> tuple[str, _Fixture]:
        return await asyncio.to_thread(self._snapshot_now)

    async def _checked(self) -> tuple[str, _Fixture]:
        """The current fingerprint and content; raises :class:`FixtureChanged` when the
        bytes changed after activation under the same declared fingerprint."""
        byte_fingerprint, fixture = await self._snapshot()
        current = fixture.declared or byte_fingerprint
        if (
            self._frozen is not None
            and self._frozen_bytes is not None
            and current == self._frozen
            and byte_fingerprint != self._frozen_bytes
        ):
            raise FixtureChanged(self.path, current, self._frozen_bytes, byte_fingerprint)
        return current, fixture

    async def activate(self) -> str:
        """Freezes and returns the fingerprint of the file as it is now: the declared one,
        or the byte fingerprint when it declares none."""
        byte_fingerprint, fixture = await self._snapshot()
        self._frozen = fixture.declared or byte_fingerprint
        self._frozen_bytes = byte_fingerprint
        return self._frozen

    async def fingerprint(self) -> str:
        return (await self._checked())[0]

    async def ticks(self, after_seq: int = 0, limit: int = DEFAULT_PAGE_SIZE) -> TickPage:
        if after_seq < 0:
            raise ValueError(f"after_seq cannot be negative, got {after_seq}")
        if not 1 <= limit <= MAX_PAGE_SIZE:
            raise ValueError(f"limit must be between 1 and {MAX_PAGE_SIZE}, got {limit}")
        fingerprint, fixture = await self._checked()
        if self._frozen is not None and fingerprint != self._frozen:
            raise FingerprintChanged(self._frozen, fingerprint)
        if fixture.ref != self._ref:
            raise FixtureError(f"the fixture now describes {fixture.ref}, not {self._ref}")
        # seq is gap-free from 1, so seq n is at index n - 1
        items: Sequence[Tick] = fixture.ticks[after_seq : after_seq + limit]
        more = after_seq + len(items) < len(fixture.ticks)
        return TickPage(
            items=items,
            next_after_seq=items[-1].seq if items and more else None,
            fingerprint=fingerprint,
        )


def file_environments(directory: Path | str) -> Callable[[EnvironmentRef], FileEnvironment]:
    """An environment factory over a directory of fixtures: ``<env_id>.json`` for a
    replay; for one simulation path ``<env_id>.path-<path_index>.json`` if present, else
    the run fixture ``<env_id>.json`` opened at that path index."""
    root = Path(directory)

    def open_environment(ref: EnvironmentRef) -> FileEnvironment:
        path = root / f"{ref.env_id}.json"
        if ref.path_index is None:
            environment = FileEnvironment(path)
        else:
            per_path = root / f"{ref.env_id}.path-{ref.path_index}.json"
            if per_path.exists():
                path = per_path
            environment = FileEnvironment(path, path_index=ref.path_index)
        if environment.ref != ref:
            raise FixtureError(f"{path} describes {environment.ref}, not {ref}")
        return environment

    return open_environment
