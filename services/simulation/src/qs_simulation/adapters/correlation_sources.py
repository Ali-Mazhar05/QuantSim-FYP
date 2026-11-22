"""Where a run reads its correlation matrix from (B16): the market service, or a recorded file."""

import json
from datetime import date
from pathlib import Path
from typing import Any
from uuid import UUID

import numpy as np

from qs_simulation.domain.runs import CORRELATION_UNAVAILABLE, RunRefused
from qs_simulation.ports import (
    CorrelationMatrix,
    CorrelationUnavailable,
    InstrumentNotFound,
    Poster,
    PriceWindowSource,
)
from qs_template.errors import ServiceError

MIN_OBSERVATIONS = 20  # fewer shared sessions leaves a cell undefined (market's own default)


def assemble(
    window: dict[str, Any], ids: list[UUID], symbols: list[str], *, n_obs: int | None = None
) -> CorrelationMatrix:
    """One market window (symbols in the market's order, cells as text or null) as a matrix in the
    order the caller asked for, with every undefined cell NaN and listed."""
    position = {symbol: i for i, symbol in enumerate(window["symbols"])}
    missing = [s for s in symbols if s not in position]
    if missing:
        raise InstrumentNotFound(", ".join(missing))
    order = [position[s] for s in symbols]
    raw = window["matrix"]
    values = np.array(
        [[np.nan if raw[r][c] is None else float(raw[r][c]) for c in order] for r in order],
        dtype=np.float64,
    )
    wanted = set(symbols)
    unavailable = tuple(
        (u["row"], u["column"], u["reason"])
        for u in window.get("unavailable", [])
        if u["row"] in wanted and u["column"] in wanted
    )
    return CorrelationMatrix(
        tuple(ids), values, int(window["n_obs"] if n_obs is None else n_obs), unavailable
    )


async def symbols_of(directory: PriceWindowSource, ids: list[UUID]) -> list[str]:
    return [(await directory.instrument(i)).symbol for i in ids]


class MarketCorrelationSource:
    """``POST /api/market/correlations`` for one window, through ``Poster`` (the service client,
    K3). Symbols come from ``directory``, because the answer names instruments by symbol."""

    def __init__(
        self, poster: Poster, directory: PriceWindowSource, *, prefix: str = "/api/market"
    ) -> None:
        self._poster = poster
        self._directory = directory
        self._prefix = prefix

    async def matrix(self, instrument_ids: list[UUID], start: date, end: date) -> CorrelationMatrix:
        symbols = await symbols_of(self._directory, instrument_ids)
        body = {
            "instrument_ids": [str(i) for i in instrument_ids],
            "windows": [{"start": start.isoformat(), "end": end.isoformat()}],
            "min_observations": MIN_OBSERVATIONS,
        }
        try:
            answer = await self._poster.post_json(f"{self._prefix}/correlations", json=body)
        except ServiceError as error:
            upstream = error.extra.get("upstream_status", error.status)
            if upstream == 404:
                raise InstrumentNotFound(
                    "an instrument is unknown to the market service"
                ) from error
            if upstream == 422:  # the market service refused this basket or window, for good
                raise RunRefused(
                    CORRELATION_UNAVAILABLE, f"the market service refused the window: {error}"
                ) from error
            raise CorrelationUnavailable(f"the market service failed: {error}") from error
        except (OSError, TimeoutError) as error:
            raise CorrelationUnavailable(
                f"the market service could not be reached: {error}"
            ) from error
        [window] = answer["windows"]
        return assemble(window, instrument_ids, symbols)


class FileCorrelationSource:
    """Reads the recorded rolling-correlation fixture (``contracts/fixtures``): the most recent
    window that ends on or before ``end`` (and starts on or after ``start`` when one does). The file
    holds windows of 60 sessions, so it answers a longer request with its latest window."""

    def __init__(self, path: Path, directory: PriceWindowSource) -> None:
        document = json.loads(path.read_text(encoding="utf-8"))
        self._windows: list[dict[str, Any]] = document["windows"]
        self._directory = directory

    async def matrix(self, instrument_ids: list[UUID], start: date, end: date) -> CorrelationMatrix:
        ending = [w for w in self._windows if date.fromisoformat(w["end"]) <= end]
        inside = [w for w in ending if date.fromisoformat(w["start"]) >= start]
        chosen = max(inside or ending, key=lambda w: w["end"], default=None)
        if chosen is None:
            raise CorrelationUnavailable(f"the file has no window ending on or before {end}")
        symbols = await symbols_of(self._directory, instrument_ids)
        return assemble(chosen, instrument_ids, symbols)
