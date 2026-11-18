"""HTTP API of the replay feed, under ``/api/market/environments`` (contract C2).

Signed-in users (``view_market_data``):          GET  /environments/{id}/ticks
Quants and admins (``create_market_environments``): POST /environments/{id}/activate

Both answer for real wherever the answer needs no feed: an unknown environment is 404, and an
environment that is not a daily replay is 422. Reading ticks and activating an environment are built
by task B12; until it lands they answer 501 with a problem body. The contract (paths, parameters,
models and errors) is therefore fixed and testable now, and B12 only replaces the 501
(ADR 01, ADR 08).
"""

import uuid
from datetime import date, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from qs_market.environments import EnvironmentService
from qs_template import Database
from qs_template.auth import Authenticator, Capability, Principal
from qs_template.errors import ServiceError

NOT_IMPLEMENTED = "urn:quantsim:problem:not-implemented"
UNSUPPORTED_FREQUENCY = "urn:quantsim:problem:unsupported-frequency"
NOT_A_REPLAY = "urn:quantsim:problem:not-a-replay-environment"

DEFAULT_PAGE = 1000
MAX_PAGE = 5000

TICK_EXAMPLE: dict[str, Any] = {
    "env_id": "6f1c2a4e-3b8d-4f7a-9c21-0a5e7d9b1c01",
    "env_type": "replay",
    "source_fingerprint": "xxh3:3f9a1c0e5b7d2a48c6e10f93b5d7a2c1",
    "seq": 1,
    "session": 0,
    "session_date": "2020-01-02",
    "ts": "2020-01-02T21:00:00Z",
    "instrument_id": "0b6d7f3a-1111-4a00-8000-000000000001",
    "symbol": "AAPL",
    "open": "73.8782285800",
    "high": "75.1500000000",
    "low": "73.7978000000",
    "close": "75.0875000000",
    "volume": "135480400.00000000",
    "path_index": None,
    "scenario": None,
}


class Tick(BaseModel):
    """One session of one instrument: the contract ``market.tick.v1`` (contracts/events)."""

    model_config = ConfigDict(json_schema_extra={"examples": [TICK_EXAMPLE]})

    env_id: uuid.UUID = Field(description="The environment (replay) or the run (synthetic)")
    env_type: Literal["replay", "synthetic"]
    source_fingerprint: str = Field(description="Identifies the exact data served")
    seq: int = Field(ge=1, description="1, 2, 3 without gaps, per environment and path")
    session: int = Field(ge=0, description="Zero-based index of the session in the environment")
    session_date: date | None = Field(default=None, description="Trading date of a replay session")
    ts: datetime = Field(description="The session close in UTC")
    instrument_id: uuid.UUID
    symbol: str
    open: str = Field(description="Adjusted, a decimal string")
    high: str
    low: str
    close: str
    volume: str
    path_index: int | None = Field(default=None, description="Null for replay")
    scenario: str | None = Field(default=None, description="Null for replay and base runs")


class TickPage(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"examples": [{"items": [TICK_EXAMPLE], "next_after_seq": 1}]}
    )

    items: list[Tick]
    next_after_seq: int | None = Field(
        description="Pass as after_seq to read the next page; null on the last page"
    )


class ActivationOut(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "environment_id": "6f1c2a4e-3b8d-4f7a-9c21-0a5e7d9b1c01",
                    "status": "active",
                    "source_fingerprint": "xxh3:3f9a1c0e5b7d2a48c6e10f93b5d7a2c1",
                    "missing_session_count": 0,
                    "activated_by": "9d1e5c7b-2222-4b00-8000-000000000001",
                    "activated_at": "2026-11-18T09:30:00Z",
                }
            ]
        }
    )

    environment_id: uuid.UUID
    status: Literal["active"]
    source_fingerprint: str = Field(description="Frozen at activation; compare with each page")
    missing_session_count: int = Field(
        ge=0, description="Sessions where some instrument has no bar (ADR 08)"
    )
    activated_by: uuid.UUID
    activated_at: datetime


def _replayable(environment: dict[str, Any]) -> None:
    """Only a daily, historical environment has a replay feed (B-FR-03)."""
    if environment["type"] != "historical_replay":
        raise ServiceError(
            422,
            "Not a replay environment",
            "Only a historical environment has a replay feed; a synthetic market is read from "
            "its simulation run.",
            type_=NOT_A_REPLAY,
        )
    if environment["frequency"] != "daily":
        raise ServiceError(
            422,
            "Only daily environments can be replayed",
            f"This environment is {environment['frequency']}; replay needs daily bars.",
            type_=UNSUPPORTED_FREQUENCY,
        )


def _not_built(what: str) -> ServiceError:
    return ServiceError(
        501,
        "Not implemented yet",
        f"{what} is part of the replay feed task (B12); the contract is final.",
        type_=NOT_IMPLEMENTED,
    )


FINGERPRINT_HEADER = {
    "X-Source-Fingerprint": {
        "description": "The fingerprint of the data on this page; it equals the value frozen at "
        "activation while the data is unchanged",
        "schema": {"type": "string"},
    }
}


def build_feed_routers(*, auth: Authenticator, database: Database) -> list[APIRouter]:
    router = APIRouter(prefix="/environments", tags=["replay feed"])

    Viewer = Annotated[Principal, Depends(auth.require_capability(Capability.VIEW_MARKET_DATA))]
    Creator = Annotated[
        Principal, Depends(auth.require_capability(Capability.CREATE_MARKET_ENVIRONMENTS))
    ]
    Session = Annotated[AsyncSession, Depends(database.session)]

    @router.get(
        "/{environment_id}/ticks",
        response_model=TickPage,
        responses={
            200: {"headers": FINGERPRINT_HEADER},
            401: {},
            403: {},
            404: {},
            422: {},
            501: {},
        },
    )
    async def read_ticks(
        environment_id: uuid.UUID,
        _: Viewer,
        session: Session,
        after_seq: Annotated[
            int, Query(ge=0, description="Return the ticks after this seq; 0 starts at the first")
        ] = 0,
        limit: Annotated[
            int, Query(ge=1, le=MAX_PAGE, description="Ticks per page")
        ] = DEFAULT_PAGE,
    ) -> TickPage:
        _replayable(await EnvironmentService(session).get(environment_id))
        raise _not_built("Reading ticks")

    @router.post(
        "/{environment_id}/activate",
        response_model=ActivationOut,
        status_code=status.HTTP_200_OK,
        responses={401: {}, 403: {}, 404: {}, 422: {}, 501: {}},
    )
    async def activate_environment(
        environment_id: uuid.UUID, _: Creator, session: Session
    ) -> ActivationOut:
        _replayable(await EnvironmentService(session).get(environment_id))
        raise _not_built("Activating an environment")

    return [router]
