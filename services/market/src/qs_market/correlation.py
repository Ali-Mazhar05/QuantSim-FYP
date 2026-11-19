"""Pearson correlation matrices over windows of aligned daily returns (FR-MKT-004).

No database and no numpy: callers pass one series per instrument and get back one matrix
per window.

Rules
-----
* The input is adjusted daily log returns, one value per session, so a split is not a
  crash. A session missing from any instrument is dropped for every instrument
  (inner join), so each window has one ``n_obs`` and every cell uses the same sessions.
* Fewer than ``min_observations`` shared sessions gives ``null`` in every cell with the
  reason ``insufficient_observations``.
* A series that is constant over the window has no correlation: its row and column
  (diagonal included) are ``null`` with the reason ``constant_series``.
* The matrix is symmetric by construction, the diagonal is exactly 1 where defined and
  every value is clamped to [-1, 1] and written as a decimal string with 8 places.

Fingerprint
-----------
sha256 of the canonical JSON (sorted keys, no spaces, ASCII) of

    version                the layout version of this document
    method, method_version "pearson-adj-log-return" and METHOD_VERSION
    instruments            the instrument ids, sorted
    start, end             the window bounds as requested
    min_observations       because it changes which cells are null
    observations           per instrument (in sorted id order), the list of
                           [session date, return as repr(float), source] over the shared
                           sessions only; ``source`` is an opaque string the caller
                           builds from the content hashes of the bars the return came
                           from, so a vendor correction changes it

The order of symbols and of windows in a request is not part of it. Two windows with the
same inputs have the same fingerprint, and a change to any value, session or bar used
changes it.
"""

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

METHOD = "pearson-adj-log-return"
METHOD_VERSION = 1
FINGERPRINT_VERSION = 1
DEFAULT_MIN_OBSERVATIONS = 20
MAX_INSTRUMENTS = 40
MAX_WINDOWS = 250
# windows x shared sessions x pairs; about a minute of work in plain Python beyond this
MAX_WORK = 20_000_000

INSUFFICIENT = "insufficient_observations"
CONSTANT = "constant_series"


class LimitExceeded(ValueError):
    """The request would need more work than one request may use."""


@dataclass(frozen=True)
class Observation:
    value: float
    source: str  # content hashes of the bars behind this return


@dataclass(frozen=True)
class Window:
    start: date
    end: date


@dataclass(frozen=True)
class Matrix:
    start: date
    end: date
    n_obs: int
    fingerprint: str
    instruments: list[str]
    values: list[list[str | None]]
    unavailable: list[tuple[str, str, str]]  # (row, column, reason), row <= column


def rolling_windows(
    sessions: Sequence[date], length: int, step: int, *, limit: int = MAX_WINDOWS
) -> list[Window]:
    """Consecutive windows of ``length`` sessions, each starting ``step`` sessions after
    the one before; only whole windows. Raises LimitExceeded past ``limit`` windows."""
    if length < 2 or step < 1:
        raise ValueError("length must be at least 2 and step at least 1")
    ordered = sorted(set(sessions))
    count = 0 if len(ordered) < length else (len(ordered) - length) // step + 1
    if count > limit:
        raise LimitExceeded(f"{count} windows, at most {limit} per request")
    return [Window(ordered[i * step], ordered[i * step + length - 1]) for i in range(count)]


def _pearson(x: list[float], y: list[float]) -> float:
    """Inputs are already centred; the value is clamped against rounding."""
    sxy = math.fsum(a * b for a, b in zip(x, y, strict=True))
    sxx = math.fsum(a * a for a in x)
    syy = math.fsum(b * b for b in y)
    value = sxy / math.sqrt(sxx * syy)
    return max(-1.0, min(1.0, value))


def _centred(values: list[float]) -> list[float] | None:
    if max(values) == min(values):
        return None
    mean = math.fsum(values) / len(values)
    centred = [v - mean for v in values]
    return centred if math.fsum(c * c for c in centred) > 0 else None


def _text(value: float) -> str:
    out = f"{value:.8f}"
    return "0.00000000" if out == "-0.00000000" else out


def fingerprint(
    ids: Sequence[str],
    window: Window,
    min_observations: int,
    observations: Mapping[str, Sequence[tuple[date, Observation]]],
) -> str:
    document = {
        "version": FINGERPRINT_VERSION,
        "method": METHOD,
        "method_version": METHOD_VERSION,
        "instruments": sorted(ids),
        "start": window.start.isoformat(),
        "end": window.end.isoformat(),
        "min_observations": min_observations,
        "observations": [
            [[d.isoformat(), repr(o.value), o.source] for d, o in observations[i]]
            for i in sorted(ids)
        ],
    }
    encoded = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("ascii")).hexdigest()


def correlate(
    series: Mapping[str, Mapping[date, Observation]],
    windows: Sequence[Window],
    *,
    labels: Mapping[str, str] | None = None,
    min_observations: int = DEFAULT_MIN_OBSERVATIONS,
) -> list[Matrix]:
    """One matrix per window, in the order given.

    ``series`` maps an instrument key (the id) to its returns by session date. Rows and
    columns are ordered by label (the symbol; the key when no labels are given), then
    key. Raises LimitExceeded when the instruments, windows or total work pass the caps.
    """
    if min_observations < 2:
        raise ValueError("min_observations must be at least 2")
    if len(series) > MAX_INSTRUMENTS:
        raise LimitExceeded(f"{len(series)} instruments, at most {MAX_INSTRUMENTS}")
    if len(windows) > MAX_WINDOWS:
        raise LimitExceeded(f"{len(windows)} windows, at most {MAX_WINDOWS}")
    # a NaN or infinite return is a missing session, like an absent one
    series = {k: {d: o for d, o in v.items() if math.isfinite(o.value)} for k, v in series.items()}
    name = labels or {}
    keys = sorted(series, key=lambda k: (name.get(k, k), k))
    names = [name.get(k, k) for k in keys]
    pairs = len(keys) * (len(keys) + 1) // 2
    shared = set.intersection(*(set(series[k]) for k in keys)) if keys else set()

    aligned: list[tuple[Window, list[date]]] = []
    work = 0
    for window in windows:
        if window.start > window.end:
            raise ValueError("window start is after its end")
        days = sorted(d for d in shared if window.start <= d <= window.end)
        work += len(days) * pairs
        if work > MAX_WORK:
            raise LimitExceeded("the windows are too long for the basket size")
        aligned.append((window, days))

    result: list[Matrix] = []
    for window, days in aligned:
        n = len(days)
        used = {k: [(d, series[k][d]) for d in days] for k in keys}
        centred: list[list[float] | None] = []
        if n >= min_observations:
            centred = [_centred([o.value for _, o in used[k]]) for k in keys]
        values: list[list[str | None]] = [[None] * len(keys) for _ in keys]
        unavailable: list[tuple[str, str, str]] = []
        for i in range(len(keys)):
            for j in range(i, len(keys)):
                cell: str | None = None
                reason: str | None = None
                if n < min_observations:
                    reason = INSUFFICIENT
                else:
                    a, b = centred[i], centred[j]
                    if a is None or b is None:
                        reason = CONSTANT
                    elif i == j:
                        cell = _text(1.0)
                    else:
                        cell = _text(_pearson(a, b))
                values[i][j] = values[j][i] = cell
                if reason is not None:
                    unavailable.append((names[i], names[j], reason))
        result.append(
            Matrix(
                start=window.start,
                end=window.end,
                n_obs=n,
                fingerprint=fingerprint(keys, window, min_observations, used),
                instruments=names,
                values=values,
                unavailable=unavailable,
            )
        )
    return result
