"""Calibration: submit a job, run it, read its outcome (B15, B-FR-08, B-FR-09).

``submit`` only validates and queues (K1), so the API answers in milliseconds. The job reads the
price window through a ``PriceWindowSource``, refuses a window that is too short before any model is
asked, fits through a ``Calibrator`` (K5) and stores the result with the fingerprint of the prices
it used. The calibration's id is the job's id: one id follows the work from queued to a stored fit.

Outcomes are four, and a client reads them from one resource:
``succeeded`` (a calibration row exists), ``refused`` (the data or the model said no: a result, not
retried), ``failed`` (the job could not finish, e.g. the market service stayed down: retried first)
and ``queued`` / ``running``.
"""

import asyncio
import math
import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from qs_simulation.domain.calibration import (
    FIT_REFUSED,
    INSTRUMENT_NOT_FOUND,
    MIN_SESSIONS,
    CalibrationRefused,
    FitResult,
    Model,
    check_window,
    input_fingerprint,
)
from qs_simulation.models import calibration, instrument_ref
from qs_simulation.ports import (
    Calibrator,
    CalibratorUnavailable,
    InstrumentNotFound,
    PriceWindowSource,
)
from qs_template import Database
from qs_template.errors import ServiceError
from qs_template.jobs import Handler, Job, JobQueue, JobState, ProgressReporter

KIND = "calibrate"
MODEL_UNAVAILABLE = "model_unavailable"
NOT_FOUND = ServiceError(
    404,
    "Calibration not found",
    "No calibration or calibration job has this id.",
    type_="urn:quantsim:problem:not-found",
)


@dataclass(frozen=True)
class CalibrationRequest:
    instrument_id: uuid.UUID
    model: Model
    window_start: date
    window_end: date


def _finite(values: dict[str, float]) -> bool:
    return all(math.isfinite(v) for v in values.values())


def _json_number(value: float) -> float | None:
    """A standard error K5 could not compute (NaN, on a parameter at its bound) is stored as null:
    JSON has no NaN."""
    return value if math.isfinite(value) else None


def check_fit(fit: FitResult) -> None:
    """A fit that is not usable is refused here, not stored: its reason is kept as the result."""
    if fit.refusal_reason:
        raise CalibrationRefused(FIT_REFUSED, fit.refusal_reason)
    if not _finite(fit.params) or not math.isfinite(fit.log_likelihood):
        raise CalibrationRefused(FIT_REFUSED, "the fit returned a parameter that is not finite")
    if not math.isfinite(fit.aic):
        raise CalibrationRefused(FIT_REFUSED, "the fit returned an AIC that is not finite")
    if fit.n_obs < MIN_SESSIONS:
        raise CalibrationRefused(
            FIT_REFUSED,
            f"the fit used {fit.n_obs} observations; at least {MIN_SESSIONS} are needed",
        )


def refusal_result(refusal: CalibrationRefused) -> dict[str, Any]:
    return {"status": "refused", "http_status": 422, "code": refusal.code, "reason": refusal.reason}


def make_handler(
    *, database: Database, source: PriceWindowSource, calibrator: Calibrator
) -> Handler:
    """The job function of kind ``calibrate``. A refusal is returned as the job's result; a price
    source that cannot be reached raises, so K1 queues the job again while attempts remain."""

    async def handle(job: Job, report: ProgressReporter) -> dict[str, Any]:
        payload = job.payload
        instrument_id = uuid.UUID(payload["instrument_id"])
        model: Model = payload["model"]
        start = date.fromisoformat(payload["window_start"])
        end = date.fromisoformat(payload["window_end"])
        try:
            info = await source.instrument(instrument_id)
            await report(0.2)
            points = check_window(await source.window(instrument_id, start, end))
            fingerprint = input_fingerprint(points)
            await report(0.5)
            fit = await asyncio.to_thread(calibrator.fit, model, points)
            check_fit(fit)
        except InstrumentNotFound:
            return refusal_result(
                CalibrationRefused(
                    INSTRUMENT_NOT_FOUND, "the market service has no such instrument"
                )
            )
        except CalibratorUnavailable as unavailable:
            return refusal_result(CalibrationRefused(MODEL_UNAVAILABLE, str(unavailable)))
        except CalibrationRefused as refusal:
            return refusal_result(refusal)
        await report(0.9)
        async with database.transaction() as session:
            await session.execute(
                insert(instrument_ref)
                .values(instrument_id=instrument_id, symbol=info.symbol, name=info.name)
                .on_conflict_do_update(
                    index_elements=[instrument_ref.c.instrument_id],
                    set_={"symbol": info.symbol, "name": info.name, "status": info.status},
                )
            )
            # a job that is run again after a crash finds its row and keeps it
            await session.execute(
                insert(calibration)
                .values(
                    id=job.id,
                    model=model,
                    instrument_id=instrument_id,
                    window_start=start,
                    window_end=end,
                    params=fit.params,
                    std_errors={k: _json_number(v) for k, v in fit.std_errors.items()},
                    log_likelihood=Decimal(repr(fit.log_likelihood)),
                    aic=Decimal(repr(fit.aic)),
                    n_obs=fit.n_obs,
                    converged=fit.converged,
                    input_fingerprint=fingerprint,
                    qs_quant_version=calibrator.version,
                    created_by=uuid.UUID(payload["created_by"]),
                )
                .on_conflict_do_nothing(index_elements=[calibration.c.id])
            )
        return {"status": "succeeded", "calibration_id": str(job.id)}

    return handle


class CalibrationService:
    def __init__(self, session: AsyncSession, queue: JobQueue, calibrator: Calibrator) -> None:
        self._session = session
        self._queue = queue
        self._calibrator = calibrator

    async def submit(
        self, request: CalibrationRequest, *, actor: uuid.UUID, idempotency_key: str | None
    ) -> tuple[uuid.UUID, bool]:
        """Queue a calibration; the same idempotency key returns the job that already exists.
        Returns the calibration id and whether it was newly queued."""
        if not self._calibrator.supports(request.model):
            raise ServiceError(
                501,
                "This model cannot be calibrated yet",
                f"The {request.model} fit is not available in this deployment.",
                type_="urn:quantsim:problem:not-implemented",
            )
        submitted = await self._queue.submit(
            self._session,
            KIND,
            {
                "instrument_id": str(request.instrument_id),
                "model": request.model,
                "window_start": request.window_start.isoformat(),
                "window_end": request.window_end.isoformat(),
                "created_by": str(actor),
            },
            idempotency_key=idempotency_key,
        )
        return submitted.id, submitted.created

    async def get(self, calibration_id: uuid.UUID) -> dict[str, Any]:
        """The calibration, or what became of its job."""
        state = await self._queue.get(self._session, calibration_id)
        if state is None or state.kind != KIND:
            raise NOT_FOUND
        stored = (
            await self._session.execute(
                select(calibration, instrument_ref.c.symbol)
                .select_from(
                    calibration.outerjoin(
                        instrument_ref,
                        instrument_ref.c.instrument_id == calibration.c.instrument_id,
                    )
                )
                .where(calibration.c.id == calibration_id)
            )
        ).first()
        return describe(state, stored)


def describe(state: JobState, stored: Any) -> dict[str, Any]:
    """One answer for every stage of a calibration."""
    base: dict[str, Any] = {
        "id": state.id,
        "progress": state.progress,
        "created_at": state.created_at,
        "finished_at": state.finished_at,
        "calibration": None,
        "refusal": None,
        "error": None,
    }
    if stored is not None:
        return {**base, "status": "succeeded", "progress": 1.0, "calibration": fit_row(stored)}
    result = state.result or {}
    if result.get("status") == "refused":
        refusal = {k: result[k] for k in ("http_status", "code", "reason")}
        return {**base, "status": "refused", "progress": 1.0, "refusal": refusal}
    if state.status == "failed":
        return {**base, "status": "failed", "error": state.error}
    return {**base, "status": "running" if state.status == "running" else "queued"}


def fit_row(stored: Any) -> dict[str, Any]:
    return {
        "model": stored.model,
        "instrument_id": stored.instrument_id,
        "symbol": stored.symbol,
        "window_start": stored.window_start,
        "window_end": stored.window_end,
        "params": stored.params,
        "std_errors": stored.std_errors,
        "log_likelihood": format(stored.log_likelihood, "f"),
        "aic": format(stored.aic, "f"),
        "n_obs": stored.n_obs,
        "converged": stored.converged,
        "input_fingerprint": stored.input_fingerprint,
        "qs_quant_version": stored.qs_quant_version,
        "created_by": stored.created_by,
        "created_at": stored.created_at,
    }
