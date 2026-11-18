"""HTTP API of simulation runs, under ``/api/simulation/runs`` (contract C2).

Every signed-in role may read. The routes are built by the Monte Carlo and read API tasks (B16,
B18); until then they answer 501 with a problem body, so the contract (paths, parameters, models
and errors) is fixed and testable now, and those tasks only replace the 501 (ADR 01, ADR 03).
"""

import uuid
from datetime import date, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field

from qs_template import Database
from qs_template.auth import Authenticator, Principal
from qs_template.errors import ServiceError

NOT_IMPLEMENTED = "urn:quantsim:problem:not-implemented"

DEFAULT_PAGE = 1000
MAX_PAGE = 5000

TICK_EXAMPLE: dict[str, Any] = {
    "env_id": "a4d3c2b1-7e6f-4a5b-8c9d-0e1f2a3b4c5d",
    "env_type": "synthetic",
    "source_fingerprint": "xxh3:9d1e0c7b5a3f2e4d6c8b0a1f3e5d7c9b",
    "seq": 1,
    "session": 0,
    "ts": "2021-01-04T21:00:00Z",
    "instrument_id": "0b6d7f3a-1111-4a00-8000-000000000001",
    "symbol": "AAPL",
    "open": "132.4100000000",
    "high": "132.4100000000",
    "low": "132.4100000000",
    "close": "132.4100000000",
    "volume": "0.00000000",
    "path_index": 0,
    "scenario": None,
}

RunStatus = Literal["queued", "running", "completed", "failed"]


class Tick(BaseModel):
    """One step of one instrument on one path: the contract ``market.tick.v1``.

    A synthetic step has a single price, so open, high, low and close are equal and volume is zero.
    """

    model_config = ConfigDict(json_schema_extra={"examples": [TICK_EXAMPLE]})

    env_id: uuid.UUID = Field(description="The run")
    env_type: Literal["replay", "synthetic"]
    source_fingerprint: str = Field(
        description="Identifies the run: its seed, configuration and code"
    )
    seq: int = Field(ge=1, description="1, 2, 3 without gaps, per path")
    session: int = Field(ge=0, description="The step, from 0")
    session_date: date | None = None
    ts: datetime = Field(description="The step's close in UTC")
    instrument_id: uuid.UUID
    symbol: str
    open: str
    high: str
    low: str
    close: str
    volume: str
    path_index: int | None = Field(default=None, description="Which path; required for synthetic")
    scenario: str | None = Field(
        default=None, description="The stress scenario, null for a base run"
    )


class TickPage(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"examples": [{"items": [TICK_EXAMPLE], "next_after_seq": 1}]}
    )

    items: list[Tick]
    next_after_seq: int | None = Field(
        description="Pass as after_seq to read the next page; null on the last page"
    )


class InstrumentStatistics(BaseModel):
    instrument_id: uuid.UUID
    symbol: str
    mean_price: str
    median_price: str
    p5_price: str
    p95_price: str
    var95: str = Field(description="A loss, as a positive decimal fraction of the start price")
    cvar95: str


class RunSummary(BaseModel):
    """A run as a picker lists it."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "id": "a4d3c2b1-7e6f-4a5b-8c9d-0e1f2a3b4c5d",
                    "status": "completed",
                    "model": "gbm",
                    "n_paths": 1000,
                    "n_steps": 252,
                    "symbols": ["AAPL", "MSFT", "NVDA"],
                    "median_path_index": 417,
                    "parent_run_id": None,
                    "scenario": None,
                    "created_at": "2026-12-01T10:00:00Z",
                }
            ]
        }
    )

    id: uuid.UUID
    status: RunStatus
    model: Literal["gbm", "ou", "merton"]
    n_paths: int
    n_steps: int
    symbols: list[str]
    median_path_index: int | None = Field(
        description="The path a portfolio binds to; set when the run completes"
    )
    parent_run_id: uuid.UUID | None = Field(description="The run a stressed run derives from")
    scenario: str | None
    created_at: datetime


class RunOut(RunSummary):
    progress: float = Field(ge=0, le=1)
    seed: int
    storage_mode: Literal["full", "quantiles"]
    statistics: list[InstrumentStatistics]
    error: str | None = None


def _not_built(what: str) -> ServiceError:
    return ServiceError(
        501,
        "Not implemented yet",
        f"{what} is part of the Monte Carlo and read API tasks (B16, B18); the contract is final.",
        type_=NOT_IMPLEMENTED,
    )


def build_run_routers(*, auth: Authenticator, database: Database) -> list[APIRouter]:
    router = APIRouter(prefix="/runs", tags=["runs"])
    Reader = Annotated[Principal, Depends(auth.principal)]

    @router.get("", response_model=list[RunSummary], responses={401: {}, 422: {}, 501: {}})
    async def list_runs(
        _: Reader,
        run_status: Annotated[
            RunStatus | None, Query(alias="status", description="Only runs in this state")
        ] = None,
        instrument: Annotated[
            uuid.UUID | None, Query(description="Only runs that include this instrument")
        ] = None,
    ) -> list[RunSummary]:
        raise _not_built("The run list")

    @router.get("/{run_id}", response_model=RunOut, responses={401: {}, 404: {}, 422: {}, 501: {}})
    async def get_run(run_id: uuid.UUID, _: Reader) -> RunOut:
        raise _not_built("The run detail")

    @router.get(
        "/{run_id}/ticks",
        response_model=TickPage,
        responses={
            200: {
                "headers": {
                    "X-Source-Fingerprint": {
                        "description": "Identifies the run; the same on every page",
                        "schema": {"type": "string"},
                    }
                }
            },
            401: {},
            404: {},
            422: {},
            501: {},
        },
    )
    async def read_path_ticks(
        run_id: uuid.UUID,
        _: Reader,
        path: Annotated[int, Query(ge=0, description="Which simulated path")] = 0,
        after_seq: Annotated[int, Query(ge=0, description="Return the ticks after this seq")] = 0,
        limit: Annotated[
            int, Query(ge=1, le=MAX_PAGE, description="Ticks per page")
        ] = DEFAULT_PAGE,
    ) -> TickPage:
        raise _not_built("The path tick feed")

    return [router]
