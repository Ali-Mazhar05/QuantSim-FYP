"""HTTP API of the instrument master, under ``/api/market``.

Signed-in users (any role, ``view_market_data``):  GET /instruments, GET /instruments/{id}
Admins (``manage_instruments``):  POST /instruments, PATCH /instruments/{id},
                                  POST /instruments/{id}/retire

When QS_SYMBOL_DIRECTORY_DIR is set, POST /instruments also checks the symbol against the
Nasdaq symbol directory.

Request bodies are validated to the same rules as the database CHECKs, so a bad body is
a 422 problem-details response and never a database error.
"""

import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Annotated, Literal, Self

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from qs_market.instruments import InstrumentService
from qs_market.symbol_directory import DirectoryError, DirectorySource, validate_new_instrument
from qs_template import Database, ServiceError
from qs_template.audit import set_audit_context
from qs_template.auth import Authenticator, Capability, Principal

SYMBOL = r"^[A-Z0-9.-]{1,15}$"
MIC = r"^[A-Z0-9]{4}$"
CURRENCY = r"^[A-Z]{3}$"


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class InstrumentCreate(_Body):
    symbol: str = Field(pattern=SYMBOL)
    name: str = Field(min_length=1, max_length=200)
    sector: str = Field(min_length=1, max_length=80)
    exchange: str = Field(pattern=MIC, description="ISO 10383 MIC, for example XNAS")
    currency: str = Field(default="USD", pattern=CURRENCY)
    asset_class: Literal["equity", "etf"]
    calendar: str = Field(default="XNYS", pattern=MIC)
    vendor_symbol: str | None = Field(default=None, pattern=r"^[A-Za-z0-9.\-]{1,20}$")
    notes: str = Field(default="", max_length=2000)


class InstrumentAnnotate(_Body):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    sector: str | None = Field(default=None, min_length=1, max_length=80)
    notes: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _something_changes(self) -> Self:
        if self.name is None and self.sector is None and self.notes is None:
            raise ValueError("send at least one of name, sector and notes")
        return self


class InstrumentSummary(BaseModel):
    """What the POC Instruments page shows, plus the keys the API needs."""

    id: uuid.UUID
    symbol: str
    name: str
    sector: str
    price: str | None = Field(description="Latest clean close, 8 decimals")
    change_pct: str | None = Field(description="Change from the previous clean close, percent")
    status: Literal["active", "retired"]
    exchange: str
    asset_class: Literal["equity", "etf"]


class InstrumentOut(InstrumentSummary):
    calendar: str
    currency: str
    vendor_symbol: str
    notes: str
    created_at: datetime
    updated_at: datetime
    retired_at: datetime | None


def build_routers(
    *, auth: Authenticator, database: Database, directory: DirectorySource | None = None
) -> list[APIRouter]:
    router = APIRouter(prefix="/instruments", tags=["instruments"])

    Viewer = Annotated[Principal, Depends(auth.require_capability(Capability.VIEW_MARKET_DATA))]
    Admin = Annotated[Principal, Depends(auth.require_capability(Capability.MANAGE_INSTRUMENTS))]
    Session = Annotated[AsyncSession, Depends(database.session)]

    async def admin_service(request: Request, actor: Admin) -> AsyncIterator[InstrumentService]:
        """A transaction whose changes the audit trail attributes to the acting admin."""
        async with database.transaction() as session:
            await set_audit_context(
                session,
                user_id=actor.user_id,
                request_id=getattr(request.state, "request_id", None),
            )
            yield InstrumentService(session, actor_id=actor.user_id)

    Writer = Annotated[InstrumentService, Depends(admin_service)]

    @router.get("", responses={401: {}, 403: {}})
    async def list_instruments(
        _: Viewer,
        session: Session,
        status_filter: Annotated[Literal["active", "retired"] | None, Query(alias="status")] = None,
    ) -> list[InstrumentSummary]:
        items = await InstrumentService(session).list(status_filter)
        return [InstrumentSummary.model_validate(item) for item in items]

    @router.get("/{instrument_id}", responses={401: {}, 403: {}, 404: {}})
    async def get_instrument(
        instrument_id: uuid.UUID, _: Viewer, session: Session
    ) -> InstrumentOut:
        return InstrumentOut.model_validate(await InstrumentService(session).get(instrument_id))

    @router.post(
        "",
        status_code=status.HTTP_201_CREATED,
        responses={401: {}, 403: {}, 409: {}, 422: {}},
    )
    async def add_instrument(body: InstrumentCreate, service: Writer) -> InstrumentOut:
        if directory is not None:
            try:
                snapshot = directory.get()
            except DirectoryError as exc:
                raise ServiceError(
                    503,
                    "Symbol directory unavailable",
                    str(exc),
                    type_="urn:quantsim:problem:symbol-directory-unavailable",
                ) from exc
            validate_new_instrument(snapshot, symbol=body.symbol, asset_class=body.asset_class)
        return InstrumentOut.model_validate(await service.add(**body.model_dump()))

    @router.patch("/{instrument_id}", responses={401: {}, 403: {}, 404: {}, 422: {}})
    async def annotate_instrument(
        instrument_id: uuid.UUID, body: InstrumentAnnotate, service: Writer
    ) -> InstrumentOut:
        return InstrumentOut.model_validate(
            await service.annotate(instrument_id, **body.model_dump())
        )

    @router.post("/{instrument_id}/retire", responses={401: {}, 403: {}, 404: {}})
    async def retire_instrument(instrument_id: uuid.UUID, service: Writer) -> InstrumentOut:
        return InstrumentOut.model_validate(await service.retire(instrument_id))

    return [router]
