"""HTTP API of calibrations, under ``/api/simulation/calibrations`` (B15, B-FR-08, B-FR-09).

Quants and admins (``calibrate_models``):  POST /calibrations              answers 202 at once
Every signed-in role:                      GET  /calibrations              the stored fits
                                           GET  /calibrations/{id}         the outcome, at any stage

The POST only validates and queues a job (K1); the fit runs in a worker. The calibration's id is the
job's id, so the id in the 202 is the id to poll. ``Idempotency-Key`` makes a repeat return
the calibration already made. A window the data or the model refuses is a ``refused`` outcome with
the reason and a 422 status inside it, not an error of the poll (DL-035).

"""

import uuid
from collections.abc import AsyncIterator
from datetime import date, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from qs_simulation.calibrations import CalibrationRequest, CalibrationService
from qs_simulation.paging import DEFAULT_PAGE, MAX_PAGE
from qs_simulation.ports import Calibrator
from qs_simulation.reads import Reads
from qs_template import Database
from qs_template.audit import set_audit_context
from qs_template.auth import Authenticator, Capability, Principal
from qs_template.errors import ServiceError
from qs_template.jobs import IdempotencyConflict, JobQueue

ModelName = Literal["gbm", "ou", "merton"]
Outcome = Literal["queued", "running", "succeeded", "refused", "failed"]

EXAMPLE: dict[str, Any] = {
    "id": "5b0e6f1c-2d3a-4c8b-9e7f-1a2b3c4d5e6f",
    "status": "succeeded",
    "progress": 1.0,
    "created_at": "2026-11-19T10:00:00Z",
    "finished_at": "2026-11-19T10:00:01Z",
    "calibration": {
        "model": "gbm",
        "instrument_id": "8d0aba1d-1737-59a8-8b52-846d1791226f",
        "symbol": "AAPL",
        "window_start": "2020-01-02",
        "window_end": "2020-12-31",
        "params": {"mu": 0.62, "sigma": 0.49},
        "std_errors": {"mu": 0.31, "sigma": 0.02},
        "log_likelihood": "694.1234567890",
        "aic": "-1384.2469135780",
        "n_obs": 252,
        "converged": True,
        "input_fingerprint": "xxh3:3f9a1c0e5b7d2a48c6e10f93b5d7a2c1",
        "qs_quant_version": "0.1.0",
        "created_by": "9d1e5c7b-2222-4b00-8000-000000000001",
        "created_at": "2026-11-19T10:00:01Z",
    },
    "refusal": None,
    "error": None,
}


class CalibrationCreate(BaseModel):
    instrument_id: uuid.UUID
    model: ModelName
    window_start: date
    window_end: date

    @model_validator(mode="after")
    def _window_is_ordered(self) -> "CalibrationCreate":
        if self.window_start >= self.window_end:
            raise ValueError("window_start must be before window_end")
        return self


class Fit(BaseModel):
    model: ModelName
    instrument_id: uuid.UUID
    symbol: str | None
    window_start: date
    window_end: date
    params: dict[str, float]
    std_errors: dict[str, float | None] = Field(
        description="Null where the fit could not compute one (a parameter on a bound)"
    )
    log_likelihood: str
    aic: str
    n_obs: int
    converged: bool
    input_fingerprint: str = Field(description="xxh3 of the ordered (session, adj_close, revision)")
    qs_quant_version: str
    created_by: uuid.UUID
    created_at: datetime


class Refusal(BaseModel):
    http_status: Literal[422] = 422
    code: str = Field(
        description="insufficient_history, fit_refused, invalid_prices, missing_adjusted_prices, "
        "instrument_not_found or model_unavailable"
    )
    reason: str = Field(description="Why, in words; for a refused fit it is the model's own")


class CalibrationOut(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [EXAMPLE]})

    id: uuid.UUID = Field(description="The calibration id, which is also its job id")
    status: Outcome
    progress: float = Field(ge=0, le=1)
    created_at: datetime
    finished_at: datetime | None
    calibration: Fit | None = Field(description="Set when status is succeeded")
    refusal: Refusal | None = Field(description="Set when status is refused")
    error: str | None = Field(description="Set when status is failed: the job could not finish")


class CalibrationPage(BaseModel):
    items: list[CalibrationOut]
    next_cursor: str | None = Field(
        description="Pass as `cursor` to read the next page; null on the last page"
    )


def build_calibration_routers(
    *,
    auth: Authenticator,
    database: Database,
    queue: JobQueue,
    calibrator: Calibrator,
    can_run: bool,
) -> list[APIRouter]:
    """``can_run`` is False when no price source is configured (the job could not do its work)."""
    router = APIRouter(prefix="/calibrations", tags=["calibrations"])
    Reader = Annotated[Principal, Depends(auth.principal)]
    QuantRole = Annotated[Principal, Depends(auth.require_capability(Capability.CALIBRATE_MODELS))]
    Session = Annotated[AsyncSession, Depends(database.session, scope="function")]

    async def writer(
        request: Request, actor: QuantRole
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
        status_code=status.HTTP_202_ACCEPTED,
        responses={401: {}, 403: {}, 409: {}, 422: {}, 501: {}, 503: {}},
    )
    async def create_calibration(
        body: CalibrationCreate,
        scope: Writer,
        response: Response,
        idempotency_key: Annotated[
            str | None,
            Header(
                alias="Idempotency-Key",
                min_length=1,
                max_length=200,
                description="Repeat a request with the same key to get the same calibration back",
            ),
        ] = None,
    ) -> CalibrationOut:
        session, actor = scope
        if not can_run:
            raise ServiceError(
                503,
                "Calibration is not available",
                "No price source is configured for this deployment.",
                type_="urn:quantsim:problem:calibration-unavailable",
            )
        service = CalibrationService(session, queue, calibrator)
        # the queue's keys are global; a caller's key is theirs alone
        scoped = None if idempotency_key is None else f"calibrate:{actor.user_id}:{idempotency_key}"
        try:
            calibration_id, _ = await service.submit(
                CalibrationRequest(**body.model_dump()), actor=actor.user_id, idempotency_key=scoped
            )
        except IdempotencyConflict as conflict:
            raise ServiceError(
                409,
                "Idempotency key already used",
                "This key belongs to a different kind of request.",
                type_="urn:quantsim:problem:idempotency-conflict",
            ) from conflict
        response.headers["Location"] = f"/api/simulation/calibrations/{calibration_id}"
        return CalibrationOut.model_validate(await service.get(calibration_id))

    @router.get("", response_model=CalibrationPage, responses={401: {}, 422: {}})
    async def list_calibrations(
        _: Reader,
        session: Session,
        instrument: Annotated[
            uuid.UUID | None, Query(description="Only calibrations of this instrument")
        ] = None,
        model: Annotated[ModelName | None, Query(description="Only this model")] = None,
        converged: Annotated[
            bool | None, Query(description="Only fits that did (true) or did not (false) converge")
        ] = None,
        limit: Annotated[
            int, Query(ge=1, le=MAX_PAGE, description="Items per page")
        ] = DEFAULT_PAGE,
        cursor: Annotated[
            str | None, Query(description="`next_cursor` of the previous page")
        ] = None,
    ) -> CalibrationPage:
        """The stored fits, newest first. A queued or refused calibration has no fit to choose, so
        it is not listed; read it by its id."""
        items, next_cursor = await Reads(session).calibrations(
            instrument=instrument, model=model, converged=converged, limit=limit, cursor=cursor
        )
        return CalibrationPage(
            items=[CalibrationOut.model_validate(i) for i in items], next_cursor=next_cursor
        )

    @router.get("/{calibration_id}", responses={401: {}, 404: {}})
    async def get_calibration(
        calibration_id: uuid.UUID, _: Reader, session: Session
    ) -> CalibrationOut:
        return CalibrationOut.model_validate(
            await CalibrationService(session, queue, calibrator).get(calibration_id)
        )

    return [router]
