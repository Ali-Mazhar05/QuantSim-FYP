"""Baskets and rolling correlation matrices, under ``/api/market``.

Signed-in users (``view_market_data``):  POST /correlations

One request names a basket (symbols or instrument ids) and either explicit windows or a
rolling schedule, and returns every window's matrix. The rules and what a fingerprint
covers are in :mod:`qs_market.correlation`. Returns are the stored adjusted log returns.
"""

import uuid
from collections import defaultdict
from datetime import date
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from qs_market import correlation
from qs_market.models import bar, instrument, return_series
from qs_template import Database, ServiceError
from qs_template.auth import Authenticator, Capability, Principal

INVALID = "urn:quantsim:problem:invalid-correlation-request"
NOT_FOUND = "urn:quantsim:problem:not-found"


class WindowIn(BaseModel):
    start: date
    end: date


class RollingIn(BaseModel):
    length: int = Field(ge=2, description="Sessions per window")
    step: int = Field(ge=1, description="Sessions between window starts")
    start: date
    end: date


class CorrelationRequest(BaseModel):
    symbols: list[str] | None = None
    instrument_ids: list[uuid.UUID] | None = None
    windows: list[WindowIn] | None = None
    rolling: RollingIn | None = None
    min_observations: int = Field(default=correlation.DEFAULT_MIN_OBSERVATIONS, ge=2, le=100000)


class Unavailable(BaseModel):
    row: str
    column: str
    reason: Literal["insufficient_observations", "constant_series"]


class MatrixOut(BaseModel):
    start: date
    end: date
    n_obs: int = Field(description="Sessions every instrument has inside the window")
    fingerprint: str
    symbols: list[str]
    matrix: list[list[str | None]] = Field(description="Pearson r, 8 decimals, null if undefined")
    unavailable: list[Unavailable] = Field(description="Why each null cell is null")


class CorrelationResponse(BaseModel):
    method: str
    method_version: int
    min_observations: int
    windows: list[MatrixOut]


def _invalid(title: str, detail: str, **extra: Any) -> ServiceError:
    return ServiceError(422, title, detail, type_=INVALID, extra=extra or None)


def _check_schedule(body: CorrelationRequest) -> None:
    if (body.windows is None) == (body.rolling is None):
        raise _invalid("Windows required", "Give windows or rolling, not both.")
    if body.windows is not None:
        if not body.windows:
            raise _invalid("No windows", "windows is empty.")
        if len(body.windows) > correlation.MAX_WINDOWS:
            raise _invalid(
                "Too many windows",
                f"{len(body.windows)} windows, at most {correlation.MAX_WINDOWS}.",
            )
        for w in body.windows:
            if w.start > w.end:
                raise _invalid("Inverted window", f"{w.start} is after {w.end}.")
    elif body.rolling is not None and body.rolling.start > body.rolling.end:
        raise _invalid("Inverted window", "rolling start is after its end.")


async def _resolve(session: AsyncSession, body: CorrelationRequest) -> dict[uuid.UUID, str]:
    """Instrument id -> symbol for the basket, or the problem to raise."""
    if (body.symbols is None) == (body.instrument_ids is None):
        raise _invalid("Basket required", "Give symbols or instrument_ids, not both.")
    found: dict[uuid.UUID, str] = {}
    if body.symbols is not None:
        wanted = [s.strip() for s in body.symbols]
        if len(set(wanted)) != len(wanted):
            raise _invalid("Duplicate symbols", "Each symbol may appear once.")
        rows = (
            await session.execute(
                select(instrument.c.id, instrument.c.symbol, instrument.c.status).where(
                    instrument.c.symbol.in_(wanted)
                )
            )
        ).all()
        by_symbol: dict[str, list[Any]] = defaultdict(list)
        for r in rows:
            by_symbol[r.symbol].append(r)
        missing = [s for s in wanted if s not in by_symbol]
        if missing:
            raise ServiceError(
                404,
                "Unknown symbols",
                f"No instrument has the symbol: {', '.join(missing)}.",
                type_=NOT_FOUND,
                extra={"unknown": missing},
            )
        for symbol in wanted:
            options = by_symbol[symbol]
            options = [r for r in options if r.status == "active"] or options
            if len(options) > 1:
                raise _invalid(
                    "Ambiguous symbol",
                    f"{symbol} is listed on more than one exchange; use instrument_ids.",
                    ambiguous=[symbol],
                )
            found[options[0].id] = symbol
    else:
        ids = body.instrument_ids or []
        if len(set(ids)) != len(ids):
            raise _invalid("Duplicate instruments", "Each instrument may appear once.")
        named = (
            await session.execute(
                select(instrument.c.id, instrument.c.symbol).where(instrument.c.id.in_(ids))
            )
        ).all()
        found = {r.id: r.symbol for r in named}
        unknown = [str(i) for i in ids if i not in found]
        if unknown:
            raise ServiceError(
                404,
                "Unknown instruments",
                f"No instrument has the id: {', '.join(unknown)}.",
                type_=NOT_FOUND,
                extra={"unknown": unknown},
            )
    if not found:
        raise _invalid("Empty basket", "The basket has no instruments.")
    if len(found) < 2:
        raise _invalid("Basket too small", "A correlation needs at least 2 instruments.")
    if len(found) > correlation.MAX_INSTRUMENTS:
        raise _invalid(
            "Basket too large",
            f"{len(found)} instruments, at most {correlation.MAX_INSTRUMENTS}.",
        )
    return found


def build_correlation_routers(*, auth: Authenticator, database: Database) -> list[APIRouter]:
    router = APIRouter(tags=["correlation"])
    Viewer = Annotated[Principal, Depends(auth.require_capability(Capability.VIEW_MARKET_DATA))]
    Session = Annotated[AsyncSession, Depends(database.session)]

    @router.post("/correlations", responses={401: {}, 403: {}, 404: {}, 422: {}})
    async def correlations(
        body: CorrelationRequest, _: Viewer, session: Session
    ) -> CorrelationResponse:
        _check_schedule(body)
        basket = await _resolve(session, body)
        if body.windows is not None:
            low = min(w.start for w in body.windows)
            high = max(w.end for w in body.windows)
        else:
            assert body.rolling is not None
            low, high = body.rolling.start, body.rolling.end

        rows = (
            await session.execute(
                select(
                    return_series.c.instrument_id,
                    return_series.c.session_date,
                    return_series.c.adj_log_return,
                )
                .where(
                    return_series.c.instrument_id.in_(list(basket)),
                    return_series.c.session_date >= low,
                    return_series.c.session_date <= high,
                    return_series.c.adj_log_return.is_not(None),
                )
                .order_by(return_series.c.instrument_id, return_series.c.session_date)
            )
        ).all()
        have = {r.instrument_id for r in rows}
        empty = sorted(s for i, s in basket.items() if i not in have)
        if empty:
            raise _invalid(
                "Instruments without returns",
                f"No returns between {low} and {high} for: {', '.join(empty)}.",
                instruments=empty,
            )

        # A return comes from its own bar and the session before, so both hashes go in
        hashes = (
            await session.execute(
                select(bar.c.instrument_id, bar.c.session_date, bar.c.content_hash)
                .where(bar.c.instrument_id.in_(list(basket)), bar.c.session_date <= high)
                .order_by(bar.c.instrument_id, bar.c.session_date)
            )
        ).all()
        sources: dict[tuple[uuid.UUID, date], str] = {}
        last: dict[uuid.UUID, str] = {}
        for h in hashes:
            sources[(h.instrument_id, h.session_date)] = (
                f"{last.get(h.instrument_id, '')}>{h.content_hash}"
            )
            last[h.instrument_id] = h.content_hash

        series: dict[str, dict[date, correlation.Observation]] = {str(i): {} for i in basket}
        for r in rows:
            series[str(r.instrument_id)][r.session_date] = correlation.Observation(
                float(r.adj_log_return), sources.get((r.instrument_id, r.session_date), "")
            )

        try:
            if body.windows is not None:
                windows = [correlation.Window(w.start, w.end) for w in body.windows]
            else:
                assert body.rolling is not None
                sessions = set.intersection(*(set(s) for s in series.values()))
                windows = correlation.rolling_windows(
                    list(sessions), body.rolling.length, body.rolling.step
                )
            matrices = correlation.correlate(
                series,
                windows,
                labels={str(i): s for i, s in basket.items()},
                min_observations=body.min_observations,
            )
        except correlation.LimitExceeded as error:
            raise _invalid("Request too large", str(error)) from error

        return CorrelationResponse(
            method=correlation.METHOD,
            method_version=correlation.METHOD_VERSION,
            min_observations=body.min_observations,
            windows=[
                MatrixOut(
                    start=m.start,
                    end=m.end,
                    n_obs=m.n_obs,
                    fingerprint=m.fingerprint,
                    symbols=m.instruments,
                    matrix=m.values,
                    unavailable=[
                        Unavailable(row=a, column=b, reason=r) for a, b, r in m.unavailable
                    ],
                )
                for m in matrices
            ],
        )

    return [router]
