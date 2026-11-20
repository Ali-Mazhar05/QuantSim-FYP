"""HTTP API of market environments, under ``/api/market/environments``.

Signed-in users (``view_market_data``):           GET /environments, GET /environments/{id}
Quants and admins (``create_market_environments``): POST /environments

The window is checked here (422) and again by the database's CHECK, so an inverted window
can never be stored (FR-MKT-008, NFR-INT-003).
"""

import uuid
from collections.abc import AsyncIterator
from datetime import date, datetime
from typing import Annotated, Literal, Self

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from qs_market.environments import EnvironmentService
from qs_template import Database
from qs_template.audit import set_audit_context
from qs_template.auth import Authenticator, Capability, Principal

EnvironmentType = Literal["historical_replay", "synthetic"]
Frequency = Literal["daily", "hourly", "tick"]


class EnvironmentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    type: EnvironmentType
    universe: str = Field(min_length=1, max_length=120)
    instrument_ids: list[uuid.UUID] = Field(min_length=1, max_length=100)
    start_date: date
    end_date: date
    frequency: Frequency = "daily"

    @model_validator(mode="after")
    def _window_is_ordered(self) -> Self:
        if self.end_date <= self.start_date:
            raise ValueError("end_date must be after start_date")
        return self


class EnvironmentOut(BaseModel):
    id: uuid.UUID
    name: str
    type: EnvironmentType
    universe: str
    instrument_ids: list[uuid.UUID]
    symbols: list[str] = Field(description="The instruments' symbols, in the given order")
    start_date: date
    end_date: date
    frequency: Frequency
    status: Literal["draft", "ready", "active"]
    created_by: uuid.UUID
    created_at: datetime
    source_fingerprint: str | None = Field(
        default=None, description="Frozen at activation; null until the environment is activated"
    )
    activated_at: datetime | None = Field(default=None, description="Null until activated")
    activated_by: uuid.UUID | None = Field(default=None, description="Null until activated")


def build_environment_routers(*, auth: Authenticator, database: Database) -> list[APIRouter]:
    router = APIRouter(prefix="/environments", tags=["environments"])

    Viewer = Annotated[Principal, Depends(auth.require_capability(Capability.VIEW_MARKET_DATA))]
    Creator = Annotated[
        Principal, Depends(auth.require_capability(Capability.CREATE_MARKET_ENVIRONMENTS))
    ]
    Session = Annotated[AsyncSession, Depends(database.session, scope="function")]

    async def writer(request: Request, actor: Creator) -> AsyncIterator[EnvironmentService]:
        async with database.transaction() as session:
            await set_audit_context(
                session,
                user_id=actor.user_id,
                request_id=getattr(request.state, "request_id", None),
            )
            yield EnvironmentService(session, actor_id=actor.user_id)

    Writer = Annotated[EnvironmentService, Depends(writer, scope="function")]

    @router.get("", responses={401: {}, 403: {}, 422: {}})
    async def list_environments(
        _: Viewer,
        session: Session,
        env_type: Annotated[
            EnvironmentType | None,
            Query(alias="type", description="Only environments of this type"),
        ] = None,
        owner: Annotated[
            uuid.UUID | None, Query(description="Only environments created by this user")
        ] = None,
    ) -> list[EnvironmentOut]:
        rows = await EnvironmentService(session).list_all(env_type=env_type, owner=owner)
        return [EnvironmentOut.model_validate(row) for row in rows]

    @router.get("/{environment_id}", responses={401: {}, 403: {}, 404: {}})
    async def get_environment(
        environment_id: uuid.UUID, _: Viewer, session: Session
    ) -> EnvironmentOut:
        return EnvironmentOut.model_validate(await EnvironmentService(session).get(environment_id))

    @router.post("", status_code=status.HTTP_201_CREATED, responses={401: {}, 403: {}, 422: {}})
    async def create_environment(body: EnvironmentCreate, service: Writer) -> EnvironmentOut:
        return EnvironmentOut.model_validate(await service.create(**body.model_dump()))

    return [router]
