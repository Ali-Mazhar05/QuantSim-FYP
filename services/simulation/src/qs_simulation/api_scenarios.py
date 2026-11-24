"""HTTP API of stress scenarios, under ``/api/simulation/scenarios`` (B17, B-FR-15, B-FR-16).

Every signed-in role:                         GET  /scenarios     the scenarios a run can have
Quants and admins (``launch_simulations``):   POST /scenarios     add one (a row of data)

Applying one to a run is ``POST /runs/{id}/scenarios`` (api_runs).
"""

import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from qs_simulation.domain.scenarios import ScenarioType
from qs_simulation.stress import ScenarioService
from qs_template import Database
from qs_template.audit import set_audit_context
from qs_template.auth import Authenticator, Capability, Principal

EXAMPLE: dict[str, Any] = {
    "id": "7c1f0b2a-3d4e-4f50-8a6b-9c0d1e2f3a4b",
    "code": "flash_crash",
    "name": "Flash crash: 20% in one step",
    "type": "price_shock",
    "params": {"drop": 0.2, "at_step": 21, "recovery_steps": 0},
    "created_at": "2026-11-22T10:00:00Z",
}


class ScenarioOut(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [EXAMPLE]})

    id: uuid.UUID
    code: str
    name: str
    type: ScenarioType
    params: dict[str, Any] = Field(
        description="price_shock: drop (0 to 1, exclusive), at_step (from 1), recovery_steps "
        "(optional); vol_multiplier: multiplier (1 to 10), from_step, to_step"
    )
    created_at: datetime


class ScenarioCreate(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{k: v for k, v in EXAMPLE.items() if k not in ("id", "created_at")}]
        }
    )

    code: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$", description="Lower case, digits, _")
    name: str = Field(min_length=1, max_length=120)
    type: ScenarioType
    params: dict[str, Any]


def build_scenario_routers(*, auth: Authenticator, database: Database) -> list[APIRouter]:
    router = APIRouter(prefix="/scenarios", tags=["scenarios"])
    Reader = Annotated[Principal, Depends(auth.principal)]
    Launcher = Annotated[Principal, Depends(auth.require_capability(Capability.LAUNCH_SIMULATIONS))]
    Session = Annotated[AsyncSession, Depends(database.session, scope="function")]

    async def writer(request: Request, actor: Launcher) -> AsyncIterator[AsyncSession]:
        async with database.transaction() as session:
            await set_audit_context(
                session,
                user_id=actor.user_id,
                request_id=getattr(request.state, "request_id", None),
            )
            yield session

    Writer = Annotated[AsyncSession, Depends(writer, scope="function")]

    @router.get("", response_model=list[ScenarioOut], responses={401: {}})
    async def list_scenarios(_: Reader, session: Session) -> list[ScenarioOut]:
        return [ScenarioOut.model_validate(s) for s in await ScenarioService(session).list()]

    @router.post(
        "",
        response_model=ScenarioOut,
        status_code=status.HTTP_201_CREATED,
        responses={401: {}, 403: {}, 409: {}, 422: {}},
    )
    async def create_scenario(
        body: ScenarioCreate, session: Writer, response: Response
    ) -> ScenarioOut:
        made = await ScenarioService(session).create(body.code, body.name, body.type, body.params)
        response.headers["Location"] = f"/api/simulation/scenarios/{made['code']}"
        return ScenarioOut.model_validate(made)

    return [router]
