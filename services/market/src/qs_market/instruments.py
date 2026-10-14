"""Instrument master: add, annotate and retire (admin), list and read (everyone).

Every write runs in the caller's audited transaction (the database trigger records the
actor) and queues its event in the same transaction, so a change and its event commit
or roll back together. Retiring never deletes: the row and its bars stay.
"""

import uuid
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Literal

from sqlalchemy import desc, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from qs_market.models import bar, instrument
from qs_template import ServiceError
from qs_template.events import EventEnvelope
from qs_template.messaging import add_event

Status = Literal["active", "retired"]

NOT_FOUND = ServiceError(
    404,
    "Instrument not found",
    "No instrument has this id.",
    type_="urn:quantsim:problem:not-found",
)

_ROW_COLUMNS = (
    instrument.c.id,
    instrument.c.symbol,
    instrument.c.name,
    instrument.c.sector,
    instrument.c.exchange,
    instrument.c.calendar,
    instrument.c.currency,
    instrument.c.asset_class,
    instrument.c.vendor_symbol,
    instrument.c.notes,
    instrument.c.status,
    instrument.c.created_at,
    instrument.c.updated_at,
    instrument.c.retired_at,
)

_NO_QUOTE: dict[str, str | None] = {"price": None, "change_pct": None}


def change_percent(latest: Decimal, previous: Decimal) -> str:
    """Percent change as an exact decimal string with two places (7.16 for 200 -> 214.32)."""
    change = (latest - previous) / previous * 100
    return str(change.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


class InstrumentService:
    def __init__(self, session: AsyncSession, *, actor_id: uuid.UUID | None = None) -> None:
        self._session = session
        self._actor = actor_id

    async def add(
        self,
        *,
        symbol: str,
        name: str,
        sector: str,
        exchange: str,
        currency: str,
        asset_class: str,
        calendar: str = "XNYS",
        vendor_symbol: str | None = None,
        notes: str = "",
    ) -> dict[str, Any]:
        existing = await self._existing(symbol, exchange)
        if existing is not None:
            raise _duplicate(*existing)
        try:
            async with self._session.begin_nested():
                row = (
                    await self._session.execute(
                        instrument.insert()
                        .values(
                            symbol=symbol,
                            name=name,
                            sector=sector,
                            exchange=exchange,
                            calendar=calendar,
                            currency=currency,
                            asset_class=asset_class,
                            vendor_symbol=vendor_symbol or symbol,
                            notes=notes,
                            status="active",
                        )
                        .returning(*_ROW_COLUMNS)
                    )
                ).one()
        except IntegrityError:  # a concurrent add won the race
            raced = await self._existing(symbol, exchange)
            if raced is None:
                raise
            raise _duplicate(*raced) from None
        result = _detail(row)
        await self._event("instrument.created", result)
        return result

    async def annotate(
        self,
        instrument_id: uuid.UUID,
        *,
        name: str | None = None,
        sector: str | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        changes = {
            k: v for k, v in (("name", name), ("sector", sector), ("notes", notes)) if v is not None
        }
        if not changes:
            return await self.get(instrument_id)
        row = (
            await self._session.execute(
                update(instrument)
                .where(instrument.c.id == instrument_id)
                .values(**changes, updated_at=datetime.now(UTC))
                .returning(*_ROW_COLUMNS)
            )
        ).first()
        if row is None:
            raise NOT_FOUND
        result = _detail(row)
        await self._event("instrument.annotated", result, changed=sorted(changes))
        return result

    async def retire(self, instrument_id: uuid.UUID) -> dict[str, Any]:
        now = datetime.now(UTC)
        row = (
            await self._session.execute(
                update(instrument)
                .where(instrument.c.id == instrument_id, instrument.c.status == "active")
                .values(status="retired", retired_at=now, updated_at=now)
                .returning(*_ROW_COLUMNS)
            )
        ).first()
        if row is None:
            # Already retired (nothing changes, no event) or unknown (404)
            return await self.get(instrument_id)
        result = _detail(row)
        await self._event("instrument.retired", result)
        return result

    async def get(self, instrument_id: uuid.UUID) -> dict[str, Any]:
        row = (
            await self._session.execute(
                select(*_ROW_COLUMNS).where(instrument.c.id == instrument_id)
            )
        ).first()
        if row is None:
            raise NOT_FOUND
        result = _detail(row)
        quotes = await self._quotes([instrument_id])
        result.update(quotes.get(instrument_id, _NO_QUOTE))
        return result

    async def _existing(self, symbol: str, exchange: str) -> tuple[uuid.UUID, str] | None:
        row = (
            await self._session.execute(
                select(instrument.c.id, instrument.c.status).where(
                    instrument.c.symbol == symbol, instrument.c.exchange == exchange
                )
            )
        ).first()
        return (row.id, row.status) if row is not None else None

    async def _quotes(self, ids: list[uuid.UUID]) -> dict[uuid.UUID, dict[str, str | None]]:
        """Price and change from the two latest bars of each instrument. Every stored bar
        has passed the cleaning gate; refused records live in ``rejected_bar``."""
        if not ids:
            return {}
        ranked = (
            select(
                bar.c.instrument_id,
                bar.c.close,
                func.row_number()
                .over(partition_by=bar.c.instrument_id, order_by=desc(bar.c.session_date))
                .label("rn"),
            )
            .where(bar.c.instrument_id.in_(ids))
            .subquery()
        )
        rows = (
            await self._session.execute(
                select(ranked.c.instrument_id, ranked.c.close)
                .where(ranked.c.rn <= 2)
                .order_by(ranked.c.instrument_id, ranked.c.rn)
            )
        ).all()
        closes: dict[uuid.UUID, list[Decimal]] = {}
        for row in rows:
            closes.setdefault(row.instrument_id, []).append(row.close)
        return {
            key: {
                "price": f"{values[0]:.8f}",
                "change_pct": change_percent(values[0], values[1]) if len(values) > 1 else None,
            }
            for key, values in closes.items()
        }

    async def _event(self, event_type: str, row: dict[str, Any], **extra: Any) -> None:
        await add_event(
            self._session,
            EventEnvelope(
                event_type=event_type,
                producer="market",
                aggregate_type="instrument",
                aggregate_id=str(row["id"]),
                data={
                    "instrument_id": str(row["id"]),
                    "symbol": row["symbol"],
                    "exchange": row["exchange"],
                    "name": row["name"],
                    "sector": row["sector"],
                    "asset_class": row["asset_class"],
                    "status": row["status"],
                    "actor_id": str(self._actor) if self._actor else None,
                    **extra,
                },
            ),
        )

    async def list(self, status: Status | None = None) -> list[dict[str, Any]]:
        query = select(*_ROW_COLUMNS).order_by(instrument.c.symbol, instrument.c.exchange)
        if status is not None:
            query = query.where(instrument.c.status == status)
        rows = (await self._session.execute(query)).all()
        quotes = await self._quotes([r.id for r in rows])
        items = []
        for row in rows:
            item = _summary(row)
            item.update(quotes.get(row.id, _NO_QUOTE))
            items.append(item)
        return items


def _duplicate(existing_id: uuid.UUID, status: str) -> ServiceError:
    return ServiceError(
        409,
        "Instrument already exists",
        f"This symbol is already listed on this exchange (status {status}).",
        type_="urn:quantsim:problem:instrument-exists",
        extra={"existing_id": str(existing_id), "existing_status": status},
    )


def _summary(row: Any) -> dict[str, Any]:
    return {
        "id": row.id,
        "symbol": row.symbol,
        "name": row.name,
        "sector": row.sector,
        "price": None,
        "change_pct": None,
        "status": row.status,
        "exchange": row.exchange,
        "asset_class": row.asset_class,
    }


def _detail(row: Any) -> dict[str, Any]:
    result = _summary(row)
    result.update(
        calendar=row.calendar,
        currency=row.currency,
        vendor_symbol=row.vendor_symbol,
        notes=row.notes,
        created_at=row.created_at,
        updated_at=row.updated_at,
        retired_at=row.retired_at,
    )
    return result
