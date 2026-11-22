"""HTTP API of simulation runs, under ``/api/simulation/runs`` (contract C2).

Quants and admins (``launch_simulations``):  POST /runs          answers 202 at once (B16)
Every signed-in role:                        GET  /runs          the list, newest first (B18)
                                             GET  /runs/{id}     state, progress, statistics (B16)
                                             GET  /runs/{id}/quantiles, /runs/{id}/ticks   (B18)

A run's id is its job's id: the 202 carries the id to poll. ``Idempotency-Key`` returns the run
that already exists. Lists page by cursor (``items`` and ``next_cursor``, as the market bars do).
"""

import uuid
from collections.abc import AsyncIterator
from datetime import date, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from qs_simulation.domain.runs import MAX_INSTRUMENTS, MIN_PATHS
from qs_simulation.models import MAX_PATHS, MAX_STEPS
from qs_simulation.paging import DEFAULT_PAGE, MAX_PAGE
from qs_simulation.ports import RiskCalculator
from qs_simulation.reads import Reads
from qs_simulation.runs import RunInstrument, RunRequest, RunService
from qs_template import Database
from qs_template.audit import set_audit_context
from qs_template.auth import Authenticator, Capability, Principal
from qs_template.errors import ServiceError
from qs_template.jobs import IdempotencyConflict, JobQueue

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


class RunInstrumentIn(BaseModel):
    instrument_id: uuid.UUID
    calibration_id: uuid.UUID = Field(
        description="A converged calibration of this instrument, of the run's model"
    )


class CorrelationWindowIn(BaseModel):
    start: date
    end: date

    @model_validator(mode="after")
    def _ordered(self) -> "CorrelationWindowIn":
        if self.start >= self.end:
            raise ValueError("start must be before end")
        return self


class RunCreate(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "model": "gbm",
                    "instruments": [
                        {
                            "instrument_id": "8d0aba1d-1737-59a8-8b52-846d1791226f",
                            "calibration_id": "5b0e6f1c-2d3a-4c8b-9e7f-1a2b3c4d5e6f",
                        }
                    ],
                    "n_paths": 1000,
                    "n_steps": 252,
                    "seed": 42,
                }
            ]
        }
    )

    model: Literal["gbm", "ou", "merton"]
    instruments: list[RunInstrumentIn] = Field(min_length=1, max_length=MAX_INSTRUMENTS)
    n_paths: int = Field(
        ge=MIN_PATHS,
        le=MAX_PATHS,
        description=f"At least {MIN_PATHS}: the risk statistics need that many returns",
    )
    n_steps: int = Field(ge=1, le=MAX_STEPS, description="Sessions to simulate")
    seed: int | None = Field(
        default=None,
        ge=0,
        lt=2**63,
        description="Same seed, same run; the server draws one when it is left out",
    )
    correlation_window: CorrelationWindowIn | None = Field(
        default=None,
        description="The sessions the correlation matrix is measured over; by default the "
        "overlap of the calibration windows",
    )


class RunPage(BaseModel):
    items: list[RunSummary]
    next_cursor: str | None = Field(
        description="Pass as `cursor` to read the next page; null on the last page"
    )


class QuantileStep(BaseModel):
    step: int = Field(ge=1, description="1 is the first simulated step, tick `session` 0")
    q01: str
    q05: str
    q25: str
    q50: str
    q75: str
    q95: str
    q99: str


class InstrumentQuantiles(BaseModel):
    instrument_id: uuid.UUID
    symbol: str
    start_price: str = Field(description="The price every path started from")
    steps: list[QuantileStep]


class QuantilesOut(BaseModel):
    """The price at each quantile of the run's paths, per step: the fan chart."""

    run_id: uuid.UUID
    n_steps: int
    levels: dict[str, str] = Field(description="The probability each column stands for")
    instruments: list[InstrumentQuantiles]


NOT_AUTHENTICATED: dict[str, Any] = {
    "description": "No token, or a bad or expired one",
    "content": {
        "application/problem+json": {
            "example": {
                "type": "urn:quantsim:problem:not-authenticated",
                "title": "Not authenticated",
                "status": 401,
                "detail": "A valid access token is required.",
            }
        }
    },
}


def build_run_routers(
    *,
    auth: Authenticator,
    database: Database,
    queue: JobQueue,
    risk: RiskCalculator,
    max_run_values: int,
    can_run: bool,
) -> list[APIRouter]:
    """``can_run`` is False when no price or correlation source is configured: the job could not do
    its work, so a run is refused up front instead of being queued for nobody."""
    router = APIRouter(prefix="/runs", tags=["runs"])
    Reader = Annotated[Principal, Depends(auth.principal)]
    Launcher = Annotated[Principal, Depends(auth.require_capability(Capability.LAUNCH_SIMULATIONS))]
    Session = Annotated[AsyncSession, Depends(database.session, scope="function")]

    def service(session: AsyncSession) -> RunService:
        return RunService(session, queue, max_run_values=max_run_values, risk=risk)

    async def writer(
        request: Request, actor: Launcher
    ) -> AsyncIterator[tuple[AsyncSession, Principal]]:
        async with database.transaction() as session:
            await set_audit_context(
                session,
                user_id=actor.user_id,
                request_id=getattr(request.state, "request_id", None),
            )
            yield session, actor

    Writer = Annotated[tuple[AsyncSession, Principal], Depends(writer, scope="function")]

    @router.post(
        "",
        response_model=RunOut,
        status_code=status.HTTP_202_ACCEPTED,
        responses={401: {}, 403: {}, 409: {}, 422: {}, 503: {}},
    )
    async def create_run(
        body: RunCreate,
        scope: Writer,
        response: Response,
        idempotency_key: Annotated[
            str | None,
            Header(
                alias="Idempotency-Key",
                min_length=1,
                max_length=200,
                description="Repeat a request with the same key to get the same run back",
            ),
        ] = None,
    ) -> RunOut:
        session, actor = scope
        if not can_run:
            raise ServiceError(
                503,
                "Simulation is not available",
                "No price or correlation source is configured for this deployment.",
                type_="urn:quantsim:problem:simulation-unavailable",
            )
        window = body.correlation_window
        request = RunRequest(
            model=body.model,
            instruments=tuple(
                RunInstrument(i.instrument_id, i.calibration_id) for i in body.instruments
            ),
            n_paths=body.n_paths,
            n_steps=body.n_steps,
            seed=body.seed,
            correlation_start=window.start if window else None,
            correlation_end=window.end if window else None,
        )
        runs = service(session)
        # the queue's keys are global; a caller's key is theirs alone
        scoped = None if idempotency_key is None else f"run:{actor.user_id}:{idempotency_key}"
        try:
            run_id, _ = await runs.submit(request, actor=actor.user_id, idempotency_key=scoped)
        except IdempotencyConflict as conflict:
            raise ServiceError(
                409,
                "Idempotency key already used",
                "This key belongs to a different kind of request.",
                type_="urn:quantsim:problem:idempotency-conflict",
            ) from conflict
        response.headers["Location"] = f"/api/simulation/runs/{run_id}"
        return RunOut.model_validate(await runs.describe(run_id))

    @router.get("", response_model=RunPage, responses={401: NOT_AUTHENTICATED, 422: {}})
    async def list_runs(
        _: Reader,
        session: Session,
        run_status: Annotated[
            RunStatus | None, Query(alias="status", description="Only runs in this state")
        ] = None,
        instrument: Annotated[
            uuid.UUID | None, Query(description="Only runs that include this instrument")
        ] = None,
        limit: Annotated[int, Query(ge=1, le=MAX_PAGE, description="Runs per page")] = DEFAULT_PAGE,
        cursor: Annotated[
            str | None, Query(description="`next_cursor` of the previous page")
        ] = None,
    ) -> RunPage:
        items, next_cursor = await Reads(session).runs(
            status=run_status, instrument=instrument, limit=limit, cursor=cursor
        )
        return RunPage(items=[RunSummary.model_validate(i) for i in items], next_cursor=next_cursor)

    @router.get(
        "/{run_id}/quantiles",
        response_model=QuantilesOut,
        responses={401: NOT_AUTHENTICATED, 404: {}, 409: {}, 422: {}},
    )
    async def read_quantiles(
        run_id: uuid.UUID,
        _: Reader,
        session: Session,
        instrument: Annotated[
            uuid.UUID | None, Query(description="Only this instrument (a long run is large)")
        ] = None,
    ) -> QuantilesOut:
        return QuantilesOut.model_validate(await Reads(session).quantiles(run_id, instrument))

    @router.get("/{run_id}", response_model=RunOut, responses={401: {}, 404: {}, 422: {}})
    async def get_run(run_id: uuid.UUID, _: Reader, session: Session) -> RunOut:
        return RunOut.model_validate(await service(session).describe(run_id))

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
            401: NOT_AUTHENTICATED,
            404: {"description": "No such run, or no such path in it (path >= n_paths)"},
            409: {"description": "The run has not completed yet, so it has no paths"},
            422: {},
        },
    )
    async def read_path_ticks(
        run_id: uuid.UUID,
        _: Reader,
        session: Session,
        response: Response,
        path: Annotated[
            int, Query(ge=0, description="Which simulated path, 0 to n_paths - 1; required")
        ],
        after_seq: Annotated[int, Query(ge=0, description="Return the ticks after this seq")] = 0,
        limit: Annotated[
            int, Query(ge=1, le=MAX_PAGE, description="Ticks per page")
        ] = DEFAULT_PAGE,
    ) -> TickPage:
        items, next_after_seq, fingerprint = await Reads(session).ticks(
            run_id, path, after_seq, limit
        )
        response.headers["X-Source-Fingerprint"] = fingerprint
        return TickPage(
            items=[Tick.model_validate(i) for i in items], next_after_seq=next_after_seq
        )

    return [router]
