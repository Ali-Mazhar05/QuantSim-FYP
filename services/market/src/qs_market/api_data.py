"""Read API for stored market data, under ``/api/market``.

Signed-in users (``view_market_data``):  GET /instruments/{id}/bars, /returns,
                                         /corporate-actions, /gaps, /quote
Admin, quant, analyst (``view_ingestion_runs``):  GET /data-quality

Every number is an exact decimal string with the stored number of places, never a float.
Lists are ascending by session date and paged by keyset: the cursor is the last session
date of the previous page, so a page costs the same however deep it is.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from qs_market.instruments import NOT_FOUND, change_percent, price_text
from qs_market.models import (
    bar,
    corporate_action,
    data_gap,
    ingestion_run,
    ingestion_run_item,
    instrument,
    rejected_bar,
    return_series,
)
from qs_template import Database, ServiceError
from qs_template.auth import Authenticator, Capability, Principal

DEFAULT_LIMIT = 500
MAX_LIMIT = 2000


def _text(value: Decimal | None) -> str | None:
    """A stored decimal exactly as stored (``format`` never switches to an exponent)."""
    return None if value is None else format(value, "f")


class BarOut(BaseModel):
    session_date: date
    open: str
    high: str
    low: str
    close: str
    volume: str
    adj_close: str | None
    quality_flags: list[str]
    revision: int
    content_hash: str


class BarPage(BaseModel):
    items: list[BarOut]
    next_cursor: date | None = Field(description="Pass as cursor to get the next page")


class ReturnOut(BaseModel):
    session_date: date
    log_return: str | None
    adj_log_return: str | None
    vol_20d: str | None
    vol_60d: str | None


class ReturnPage(BaseModel):
    items: list[ReturnOut]
    next_cursor: date | None


class CorporateActionOut(BaseModel):
    session_date: date
    kind: Literal["split", "dividend", "split_and_dividend"]
    split_factor: str
    dividend: str


class GapOut(BaseModel):
    session_date: date
    status: Literal["open", "resolved"]
    opened_at: datetime
    resolved_at: datetime | None


class DataQualityRow(BaseModel):
    instrument_id: uuid.UUID
    symbol: str
    last_session: date | None
    bar_count: int
    open_gaps: int
    flagged_bars: int
    rejected_total: int
    last_run_id: uuid.UUID | None
    last_run_status: str | None


class QuoteOut(BaseModel):
    instrument_id: uuid.UUID
    price: str | None = Field(description="Latest clean close, 8 decimals")
    previous_close: str | None
    change_pct: str | None = Field(description="Percent change from the previous close")
    as_of: date | None = Field(description="Session date of the latest close")


def _check_window(start: date | None, end: date | None) -> None:
    if start is not None and end is not None and start > end:
        raise ServiceError(
            422,
            "Inverted date range",
            "from must not be after to.",
            type_="urn:quantsim:problem:invalid-range",
        )


def _paged(
    query: Select[Any],
    column: Any,
    *,
    start: date | None,
    end: date | None,
    cursor: date | None,
    limit: int,
) -> Select[Any]:
    """Ascending by session, one row beyond the limit so the caller knows another page
    exists."""
    if start is not None:
        query = query.where(column >= start)
    if end is not None:
        query = query.where(column <= end)
    if cursor is not None:
        query = query.where(column > cursor)
    return query.order_by(column).limit(limit + 1)


def build_data_routers(*, auth: Authenticator, database: Database) -> list[APIRouter]:
    router = APIRouter(tags=["market data"])

    Viewer = Annotated[Principal, Depends(auth.require_capability(Capability.VIEW_MARKET_DATA))]
    Inspector = Annotated[
        Principal, Depends(auth.require_capability(Capability.VIEW_INGESTION_RUNS))
    ]
    Session = Annotated[AsyncSession, Depends(database.session)]
    From = Annotated[date | None, Query(alias="from", description="First session, inclusive")]
    To = Annotated[date | None, Query(description="Last session, inclusive")]
    Cursor = Annotated[date | None, Query(description="next_cursor of the previous page")]
    Limit = Annotated[int, Query(ge=1, le=MAX_LIMIT)]

    async def known(session: AsyncSession, instrument_id: uuid.UUID) -> None:
        found = await session.execute(
            select(instrument.c.id).where(instrument.c.id == instrument_id)
        )
        if found.first() is None:
            raise NOT_FOUND

    @router.get("/instruments/{instrument_id}/bars", responses={401: {}, 403: {}, 404: {}, 422: {}})
    async def list_bars(
        instrument_id: uuid.UUID,
        _: Viewer,
        session: Session,
        start: From = None,
        to: To = None,
        cursor: Cursor = None,
        limit: Limit = DEFAULT_LIMIT,
    ) -> BarPage:
        _check_window(start, to)
        await known(session, instrument_id)
        query = select(
            bar.c.session_date,
            bar.c.open,
            bar.c.high,
            bar.c.low,
            bar.c.close,
            bar.c.volume,
            bar.c.adj_close,
            bar.c.quality_flags,
            bar.c.revision,
            bar.c.content_hash,
        ).where(bar.c.instrument_id == instrument_id)
        rows = (
            await session.execute(
                _paged(query, bar.c.session_date, start=start, end=to, cursor=cursor, limit=limit)
            )
        ).all()
        page = rows[:limit]
        return BarPage(
            items=[
                BarOut(
                    session_date=r.session_date,
                    open=format(r.open, "f"),
                    high=format(r.high, "f"),
                    low=format(r.low, "f"),
                    close=format(r.close, "f"),
                    volume=format(r.volume, "f"),
                    adj_close=_text(r.adj_close),
                    quality_flags=list(r.quality_flags),
                    revision=r.revision,
                    content_hash=r.content_hash,
                )
                for r in page
            ],
            next_cursor=page[-1].session_date if len(rows) > limit else None,
        )

    @router.get(
        "/instruments/{instrument_id}/returns", responses={401: {}, 403: {}, 404: {}, 422: {}}
    )
    async def list_returns(
        instrument_id: uuid.UUID,
        _: Viewer,
        session: Session,
        start: From = None,
        to: To = None,
        cursor: Cursor = None,
        limit: Limit = DEFAULT_LIMIT,
    ) -> ReturnPage:
        _check_window(start, to)
        await known(session, instrument_id)
        query = select(
            return_series.c.session_date,
            return_series.c.log_return,
            return_series.c.adj_log_return,
            return_series.c.vol_20d,
            return_series.c.vol_60d,
        ).where(return_series.c.instrument_id == instrument_id)
        rows = (
            await session.execute(
                _paged(
                    query,
                    return_series.c.session_date,
                    start=start,
                    end=to,
                    cursor=cursor,
                    limit=limit,
                )
            )
        ).all()
        page = rows[:limit]
        return ReturnPage(
            items=[
                ReturnOut(
                    session_date=r.session_date,
                    log_return=_text(r.log_return),
                    adj_log_return=_text(r.adj_log_return),
                    vol_20d=_text(r.vol_20d),
                    vol_60d=_text(r.vol_60d),
                )
                for r in page
            ],
            next_cursor=page[-1].session_date if len(rows) > limit else None,
        )

    @router.get(
        "/instruments/{instrument_id}/corporate-actions", responses={401: {}, 403: {}, 404: {}}
    )
    async def list_corporate_actions(
        instrument_id: uuid.UUID, _: Viewer, session: Session
    ) -> list[CorporateActionOut]:
        await known(session, instrument_id)
        rows = (
            await session.execute(
                select(
                    corporate_action.c.session_date,
                    corporate_action.c.split_factor,
                    corporate_action.c.dividend,
                )
                .where(corporate_action.c.instrument_id == instrument_id)
                .order_by(corporate_action.c.session_date)
            )
        ).all()
        out: list[CorporateActionOut] = []
        for r in rows:
            splits, pays = r.split_factor != 1, r.dividend > 0
            kind: Literal["split", "dividend", "split_and_dividend"] = (
                "split_and_dividend" if splits and pays else "split" if splits else "dividend"
            )
            out.append(
                CorporateActionOut(
                    session_date=r.session_date,
                    kind=kind,
                    split_factor=format(r.split_factor, "f"),
                    dividend=format(r.dividend, "f"),
                )
            )
        return out

    @router.get("/instruments/{instrument_id}/gaps", responses={401: {}, 403: {}, 404: {}})
    async def list_gaps(
        instrument_id: uuid.UUID,
        _: Viewer,
        session: Session,
        status_filter: Annotated[Literal["open", "resolved"] | None, Query(alias="status")] = None,
    ) -> list[GapOut]:
        await known(session, instrument_id)
        query = (
            select(data_gap.c.session_date, data_gap.c.opened_at, data_gap.c.resolved_at)
            .where(data_gap.c.instrument_id == instrument_id)
            .order_by(data_gap.c.session_date)
        )
        if status_filter == "open":
            query = query.where(data_gap.c.resolved_at.is_(None))
        elif status_filter == "resolved":
            query = query.where(data_gap.c.resolved_at.is_not(None))
        return [
            GapOut(
                session_date=r.session_date,
                status="open" if r.resolved_at is None else "resolved",
                opened_at=r.opened_at,
                resolved_at=r.resolved_at,
            )
            for r in (await session.execute(query)).all()
        ]

    @router.get("/instruments/{instrument_id}/quote", responses={401: {}, 403: {}, 404: {}})
    async def quote(instrument_id: uuid.UUID, _: Viewer, session: Session) -> QuoteOut:
        await known(session, instrument_id)
        rows = (
            await session.execute(
                select(bar.c.session_date, bar.c.close)
                .where(bar.c.instrument_id == instrument_id)
                .order_by(bar.c.session_date.desc())
                .limit(2)
            )
        ).all()
        if not rows:
            return QuoteOut(
                instrument_id=instrument_id,
                price=None,
                previous_close=None,
                change_pct=None,
                as_of=None,
            )
        latest = rows[0]
        previous = rows[1].close if len(rows) > 1 else None
        return QuoteOut(
            instrument_id=instrument_id,
            price=price_text(latest.close),
            previous_close=price_text(previous) if previous is not None else None,
            change_pct=change_percent(latest.close, previous) if previous is not None else None,
            as_of=latest.session_date,
        )

    @router.get("/data-quality", responses={401: {}, 403: {}})
    async def data_quality(_: Inspector, session: Session) -> list[DataQualityRow]:
        """One row per active instrument: four grouped scans joined once, not one query
        per instrument."""
        bars = (
            select(
                bar.c.instrument_id,
                func.max(bar.c.session_date).label("last_session"),
                func.count().label("bar_count"),
                func.count()
                .filter(func.jsonb_array_length(bar.c.quality_flags) > 0)
                .label("flagged_bars"),
            )
            .group_by(bar.c.instrument_id)
            .subquery()
        )
        gaps = (
            select(data_gap.c.instrument_id, func.count().label("open_gaps"))
            .where(data_gap.c.resolved_at.is_(None))
            .group_by(data_gap.c.instrument_id)
            .subquery()
        )
        rejected = (
            select(rejected_bar.c.instrument_id, func.count().label("rejected_total"))
            .group_by(rejected_bar.c.instrument_id)
            .subquery()
        )
        ranked = (
            select(
                ingestion_run_item.c.instrument_id,
                ingestion_run.c.id.label("run_id"),
                ingestion_run.c.status.label("run_status"),
                func.row_number()
                .over(
                    partition_by=ingestion_run_item.c.instrument_id,
                    order_by=(ingestion_run.c.created_at.desc(), ingestion_run.c.id.desc()),
                )
                .label("rn"),
            )
            .select_from(
                ingestion_run_item.join(
                    ingestion_run, ingestion_run.c.id == ingestion_run_item.c.run_id
                )
            )
            .subquery()
        )
        last_run = select(ranked).where(ranked.c.rn == 1).subquery()
        query = (
            select(
                instrument.c.id,
                instrument.c.symbol,
                bars.c.last_session,
                func.coalesce(bars.c.bar_count, 0).label("bar_count"),
                func.coalesce(gaps.c.open_gaps, 0).label("open_gaps"),
                func.coalesce(bars.c.flagged_bars, 0).label("flagged_bars"),
                func.coalesce(rejected.c.rejected_total, 0).label("rejected_total"),
                last_run.c.run_id,
                last_run.c.run_status,
            )
            .select_from(instrument)
            .outerjoin(bars, bars.c.instrument_id == instrument.c.id)
            .outerjoin(gaps, gaps.c.instrument_id == instrument.c.id)
            .outerjoin(rejected, rejected.c.instrument_id == instrument.c.id)
            .outerjoin(last_run, last_run.c.instrument_id == instrument.c.id)
            .where(instrument.c.status == "active", instrument.c.is_fixture.is_(False))
            .order_by(instrument.c.symbol, instrument.c.exchange)
        )
        return [
            DataQualityRow(
                instrument_id=r.id,
                symbol=r.symbol,
                last_session=r.last_session,
                bar_count=r.bar_count,
                open_gaps=r.open_gaps,
                flagged_bars=r.flagged_bars,
                rejected_total=r.rejected_total,
                last_run_id=r.run_id,
                last_run_status=r.run_status,
            )
            for r in (await session.execute(query)).all()
        ]

    return [router]
