"""HTTP API of replay sessions, under ``/api/market/replay-sessions`` (B13, B-FR-06).

Signed-in users (``view_market_data``):             GET  /replay-sessions, GET /replay-sessions/{id}
Quants and admins (``create_market_environments``): POST /replay-sessions,
                                                    POST /replay-sessions/{id}/control

A session is a server-side clock over an activated environment (DL-003). Every read returns the
position computed at that moment, with the server time it was computed at, so a page can poll and
animate between polls, and a reload resumes where the server says the clock is. Controls are one
route with an ``action`` (play, pause, speed, seek). Pushing the position over SSE was cut; polling
is the accepted way (DL-034).
"""

import uuid
from collections.abc import AsyncIterator
from datetime import date, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from qs_market.replay_sessions import Clock, ReplaySessionService, utc_now
from qs_template import Database
from qs_template.audit import set_audit_context
from qs_template.auth import Authenticator, Capability, Principal

Speed = Literal[1, 5, 20]

SESSION_EXAMPLE: dict[str, Any] = {
    "id": "3c1d9a52-7e64-4b0f-9a88-5d2e6f1b7c10",
    "environment_id": "6f1c2a4e-3b8d-4f7a-9c21-0a5e7d9b1c01",
    "state": "playing",
    "speed": 5,
    "position": 42,
    "session_count": 253,
    "session_date": "2020-03-02",
    "finished": False,
    "source_fingerprint": "xxh3:3f9a1c0e5b7d2a48c6e10f93b5d7a2c1",
    "current_fingerprint": "xxh3:3f9a1c0e5b7d2a48c6e10f93b5d7a2c1",
    "server_time": "2026-11-19T09:30:02Z",
    "created_by": "9d1e5c7b-2222-4b00-8000-000000000001",
    "created_at": "2026-11-19T09:29:00Z",
    "updated_at": "2026-11-19T09:29:50Z",
}


class SessionCreate(BaseModel):
    environment_id: uuid.UUID = Field(description="An activated daily replay environment")
    speed: Speed = Field(default=1, description="Sessions per second: 1, 5 or 20")


class Play(BaseModel):
    action: Literal["play"]


class Pause(BaseModel):
    action: Literal["pause"]


class SetSpeed(BaseModel):
    action: Literal["speed"]
    speed: Speed


class Seek(BaseModel):
    action: Literal["seek"]
    index: int = Field(
        description="Zero-based session index; clamped to the first and last session of the window"
    )


Control = Annotated[Play | Pause | SetSpeed | Seek, Field(discriminator="action")]


class SessionOut(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [SESSION_EXAMPLE]})

    id: uuid.UUID
    environment_id: uuid.UUID
    state: Literal["playing", "paused"]
    speed: Speed
    position: int = Field(ge=0, description="Zero-based session index the clock stands at now")
    session_count: int = Field(
        ge=1, description="Sessions in the window; the last index is one less"
    )
    session_date: date | None = Field(description="Trading date at the position")
    finished: bool = Field(description="Playing and the clock has reached the last session")
    source_fingerprint: str = Field(description="The data the session was created on (ADR 08)")
    current_fingerprint: str | None = Field(
        description="The environment's frozen fingerprint now; different if it was activated again"
    )
    server_time: datetime = Field(description="The server time the position was computed at")
    created_by: uuid.UUID
    created_at: datetime
    updated_at: datetime


def build_replay_routers(
    *, auth: Authenticator, database: Database, clock: Clock = utc_now
) -> list[APIRouter]:
    router = APIRouter(prefix="/replay-sessions", tags=["replay sessions"])

    Viewer = Annotated[Principal, Depends(auth.require_capability(Capability.VIEW_MARKET_DATA))]
    Creator = Annotated[
        Principal, Depends(auth.require_capability(Capability.CREATE_MARKET_ENVIRONMENTS))
    ]
    Session = Annotated[AsyncSession, Depends(database.session, scope="function")]

    async def writer(request: Request, actor: Creator) -> AsyncIterator[ReplaySessionService]:
        async with database.transaction() as session:
            await set_audit_context(
                session,
                user_id=actor.user_id,
                request_id=getattr(request.state, "request_id", None),
            )
            yield ReplaySessionService(session, actor_id=actor.user_id, clock=clock)

    Writer = Annotated[ReplaySessionService, Depends(writer, scope="function")]

    @router.get("", responses={401: {}, 403: {}})
    async def list_sessions(
        _: Viewer,
        session: Session,
        environment_id: Annotated[
            uuid.UUID | None, Query(description="Only the sessions of this environment")
        ] = None,
    ) -> list[SessionOut]:
        rows = await ReplaySessionService(session, clock=clock).list_for(environment_id)
        return [SessionOut.model_validate(row) for row in rows]

    @router.get("/{session_id}", responses={401: {}, 403: {}, 404: {}})
    async def get_session(session_id: uuid.UUID, _: Viewer, session: Session) -> SessionOut:
        return SessionOut.model_validate(
            await ReplaySessionService(session, clock=clock).get(session_id)
        )

    @router.post(
        "",
        status_code=status.HTTP_201_CREATED,
        responses={401: {}, 403: {}, 404: {}, 422: {}},
    )
    async def create_session(body: SessionCreate, service: Writer) -> SessionOut:
        return SessionOut.model_validate(await service.create(body.environment_id, body.speed))

    @router.post("/{session_id}/control", responses={401: {}, 403: {}, 404: {}, 422: {}})
    async def control_session(session_id: uuid.UUID, body: Control, service: Writer) -> SessionOut:
        if isinstance(body, SetSpeed):
            result = await service.control(session_id, "speed", speed=body.speed)
        elif isinstance(body, Seek):
            result = await service.control(session_id, "seek", index=body.index)
        else:
            result = await service.control(session_id, body.action)
        return SessionOut.model_validate(result)

    return [router]
