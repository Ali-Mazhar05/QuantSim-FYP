"""HTTP API of the replay feed, under ``/api/market/environments`` (contract C2).

Signed-in users (``view_market_data``):          GET  /environments/{id}/ticks
Quants and admins (``create_market_environments``): POST /environments/{id}/activate

Ticks are the adjusted daily bars of the environment's instruments in its window, ordered by
(session, symbol) with a gap-free ``seq`` and read by ``after_seq`` (ADR 01); every page carries the
fingerprint of the data served, and activation freezes it (ADR 08). An unknown environment is 404;
that is not a daily replay, is not ready, or has a bar without adjusted prices is 422.
"""

import uuid
from collections.abc import AsyncIterator
from datetime import date, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from qs_market.api_data import DEFAULT_LIMIT, MAX_LIMIT
from qs_market.replay import ReplayService
from qs_template import Database
from qs_template.audit import set_audit_context
from qs_template.auth import Authenticator, Capability, Principal

DEFAULT_PAGE = DEFAULT_LIMIT  # the market service pages every list the same way (api_data.py)
MAX_PAGE = MAX_LIMIT

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


NOT_REPLAYABLE = {
    "description": "A bad parameter, or an environment that cannot be replayed: "
    "unsupported-frequency, not-a-replay-environment, or missing-adjusted-prices with the bar "
    "count per symbol in `missing`"
}

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
    Session = Annotated[AsyncSession, Depends(database.session, scope="function")]

    async def writer(
        request: Request, actor: Creator
    ) -> AsyncIterator[tuple[AsyncSession, Principal]]:
        async with database.transaction() as session:
            await set_audit_context(
                session,
                user_id=actor.user_id,
                request_id=getattr(request.state, "request_id", None),
            )
            yield session, actor

    Writer = Annotated[tuple[AsyncSession, Principal], Depends(writer)]

    @router.get(
        "/{environment_id}/ticks",
        response_model=TickPage,
        responses={
            200: {"headers": FINGERPRINT_HEADER},
            401: {},
            403: {},
            404: {},
            422: NOT_REPLAYABLE,
        },
    )
    async def read_ticks(
        environment_id: uuid.UUID,
        _: Viewer,
        session: Session,
        response: Response,
        after_seq: Annotated[
            int, Query(ge=0, description="Return the ticks after this seq; 0 starts at the first")
        ] = 0,
        limit: Annotated[
            int, Query(ge=1, le=MAX_PAGE, description="Ticks per page")
        ] = DEFAULT_PAGE,
    ) -> TickPage:
        items, next_after_seq, fingerprint = await ReplayService(session).ticks(
            environment_id, after_seq, limit
        )
        response.headers["X-Source-Fingerprint"] = fingerprint
        return TickPage(
            items=[Tick.model_validate(item) for item in items], next_after_seq=next_after_seq
        )

    @router.post(
        "/{environment_id}/activate",
        response_model=ActivationOut,
        status_code=status.HTTP_200_OK,
        responses={401: {}, 403: {}, 404: {}, 422: NOT_REPLAYABLE},
    )
    async def activate_environment(environment_id: uuid.UUID, scope: Writer) -> ActivationOut:
        session, actor = scope
        frozen = await ReplayService(session, actor_id=actor.user_id).activate(environment_id)
        return ActivationOut.model_validate(frozen)

    return [router]
