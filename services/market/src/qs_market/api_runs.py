"""HTTP API of the ingestion runs, under ``/api/market``.

Admins (``trigger_ingestion`` and ``backfill_market_data``):  POST /ingestion-runs
Admin, quant, analyst (``view_ingestion_runs``):  GET /ingestion-runs,
    GET /ingestion-runs/{id}, GET /ingestion-runs/{id}/rejected

A POST only queues the run and answers 202; the worker executes it.
"""

import uuid
from collections.abc import AsyncIterator
from datetime import date, datetime
from typing import Annotated, Any, Literal, Self

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from qs_market.models import ingestion_run, ingestion_run_item, instrument, rejected_bar
from qs_market.pipeline.runs import RunConflict, create_run
from qs_template import Database, ServiceError
from qs_template.audit import set_audit_context
from qs_template.auth import Authenticator, Capability, Principal

RunStatus = Literal["pending", "running", "succeeded", "partially_succeeded", "failed"]

RUN_NOT_FOUND = ServiceError(
    404,
    "Ingestion run not found",
    "No ingestion run has this id.",
    type_="urn:quantsim:problem:not-found",
)


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["manual", "backfill"]
    start: date | None = None
    end: date | None = None
    instrument_ids: list[uuid.UUID] | None = Field(default=None, min_length=1)
    # The same thing by ticker, for people and scripts that do not know the ids
    symbols: list[str] | None = Field(default=None, min_length=1)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=200)

    @model_validator(mode="after")
    def _window_makes_sense(self) -> Self:
        if self.start and self.end and self.start > self.end:
            raise ValueError("start must not be after end")
        if self.instrument_ids is not None and self.symbols is not None:
            raise ValueError("give instrument_ids or symbols, not both")
        if self.mode == "backfill" and self.start is None:
            raise ValueError("a backfill needs a start date")
        return self


class RunAccepted(BaseModel):
    id: uuid.UUID
    status: RunStatus
    created: bool = Field(description="False when the idempotency key already had a run")


class RunSummary(BaseModel):
    id: uuid.UUID
    mode: str
    status: RunStatus
    vendor: str
    requested_by: str
    window_start: date | None
    window_end: date | None
    instrument_ids: list[uuid.UUID] | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class RunItem(BaseModel):
    instrument_id: uuid.UUID
    symbol: str
    status: str
    received: int
    passed_untouched: int
    corrected: int
    duplicates_removed: int
    rejected: int
    new_bars: int
    revised: int
    gaps_opened: int
    gaps_resolved: int
    error: str | None
    report: dict[str, Any] | None


class RunDetail(RunSummary):
    ruleset_version: str | None
    error: str | None
    report: dict[str, Any] | None
    items: list[RunItem]


class RejectedBar(BaseModel):
    id: int
    instrument_id: uuid.UUID
    symbol: str
    session_date: date | None
    rules: list[str]
    payload: dict[str, Any]
    rejected_at: datetime


class RejectedPage(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[RejectedBar]


def _summary(row: Any) -> RunSummary:
    ids = None if row.instrument_ids is None else [uuid.UUID(i) for i in row.instrument_ids]
    return RunSummary(
        id=row.id,
        mode=row.mode,
        status=row.status,
        vendor=row.vendor,
        requested_by=row.requested_by,
        window_start=row.window_start,
        window_end=row.window_end,
        instrument_ids=ids,
        created_at=row.created_at,
        started_at=row.started_at,
        finished_at=row.finished_at,
    )


def build_routers(*, auth: Authenticator, database: Database, vendor: str) -> list[APIRouter]:
    router = APIRouter(prefix="/ingestion-runs", tags=["ingestion-runs"])

    Admin = Annotated[
        Principal,
        Depends(
            auth.require_capability(Capability.TRIGGER_INGESTION, Capability.BACKFILL_MARKET_DATA)
        ),
    ]
    Reader = Annotated[Principal, Depends(auth.require_capability(Capability.VIEW_INGESTION_RUNS))]
    Session = Annotated[AsyncSession, Depends(database.session)]

    async def audited_session(request: Request, actor: Admin) -> AsyncIterator[AsyncSession]:
        async with database.transaction() as session:
            await set_audit_context(
                session,
                user_id=actor.user_id,
                request_id=getattr(request.state, "request_id", None),
            )
            yield session

    Writer = Annotated[AsyncSession, Depends(audited_session)]

    @router.post(
        "",
        status_code=status.HTTP_202_ACCEPTED,
        responses={401: {}, 403: {}, 409: {}, 422: {}},
    )
    async def enqueue_run(body: RunRequest, actor: Admin, session: Writer) -> RunAccepted:
        instrument_ids = body.instrument_ids
        if body.symbols is not None:
            symbols = {s.strip().upper() for s in body.symbols}
            found = {
                row.symbol: row.id
                for row in await session.execute(
                    select(instrument.c.symbol, instrument.c.id).where(
                        instrument.c.symbol.in_(symbols)
                    )
                )
            }
            if missing_symbols := sorted(symbols - set(found)):
                raise ServiceError(
                    422,
                    "Unknown instruments",
                    f"No instrument has the symbol {', '.join(missing_symbols)}.",
                    type_="urn:quantsim:problem:validation",
                    extra={"unknown_symbols": missing_symbols},
                )
            instrument_ids = list(found.values())
        if instrument_ids is not None:
            wanted = set(instrument_ids)
            known = set(
                (await session.execute(select(instrument.c.id).where(instrument.c.id.in_(wanted))))
                .scalars()
                .all()
            )
            if missing := sorted(str(i) for i in wanted - known):
                raise ServiceError(
                    422,
                    "Unknown instruments",
                    f"No instrument has the id {', '.join(missing)}.",
                    type_="urn:quantsim:problem:validation",
                    extra={"unknown_instrument_ids": missing},
                )
        try:
            created = await create_run(
                session,
                mode=body.mode,
                window=(body.start, body.end) if body.start or body.end else None,
                instrument_ids=instrument_ids,
                idempotency_key=body.idempotency_key,
                requested_by=str(actor.user_id),
                vendor=vendor,
            )
        except RunConflict as exc:
            raise ServiceError(
                409,
                "Run already active",
                str(exc),
                type_="urn:quantsim:problem:run-conflict",
                extra={"active_run_id": str(exc.run_id)},
            ) from None
        current = (
            await session.execute(
                select(ingestion_run.c.status).where(ingestion_run.c.id == created.id)
            )
        ).scalar_one()
        return RunAccepted(id=created.id, status=current, created=created.created)

    @router.get("", responses={401: {}, 403: {}})
    async def list_runs(
        _: Reader,
        session: Session,
        status_filter: Annotated[RunStatus | None, Query(alias="status")] = None,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
    ) -> list[RunSummary]:
        query = select(ingestion_run).order_by(
            ingestion_run.c.created_at.desc(), ingestion_run.c.id
        )
        if status_filter:
            query = query.where(ingestion_run.c.status == status_filter)
        rows = (await session.execute(query.limit(limit))).all()
        return [_summary(r) for r in rows]

    @router.get("/{run_id}", responses={401: {}, 403: {}, 404: {}})
    async def get_run(run_id: uuid.UUID, _: Reader, session: Session) -> RunDetail:
        row = (
            await session.execute(select(ingestion_run).where(ingestion_run.c.id == run_id))
        ).first()
        if row is None:
            raise RUN_NOT_FOUND
        items = (
            await session.execute(
                select(ingestion_run_item, instrument.c.symbol)
                .join(instrument, instrument.c.id == ingestion_run_item.c.instrument_id)
                .where(ingestion_run_item.c.run_id == run_id)
                .order_by(instrument.c.symbol)
            )
        ).all()
        return RunDetail(
            **_summary(row).model_dump(),
            ruleset_version=row.ruleset_version,
            error=row.error,
            report=row.report,
            items=[RunItem.model_validate(i, from_attributes=True) for i in items],
        )

    @router.get("/{run_id}/rejected", responses={401: {}, 403: {}, 404: {}})
    async def rejected_bars(
        run_id: uuid.UUID,
        _: Reader,
        session: Session,
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> RejectedPage:
        exists = (
            await session.execute(select(ingestion_run.c.id).where(ingestion_run.c.id == run_id))
        ).first()
        if exists is None:
            raise RUN_NOT_FOUND
        total = (
            await session.execute(
                select(func.count())
                .select_from(rejected_bar)
                .where(rejected_bar.c.run_id == run_id)
            )
        ).scalar_one()
        rows = (
            await session.execute(
                select(rejected_bar, instrument.c.symbol)
                .join(instrument, instrument.c.id == rejected_bar.c.instrument_id)
                .where(rejected_bar.c.run_id == run_id)
                .order_by(instrument.c.symbol, rejected_bar.c.session_date, rejected_bar.c.id)
                .limit(limit)
                .offset(offset)
            )
        ).all()
        return RejectedPage(
            total=total,
            limit=limit,
            offset=offset,
            items=[RejectedBar.model_validate(r, from_attributes=True) for r in rows],
        )

    return [router]
