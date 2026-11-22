"""Stressed runs and the scenarios they apply (B17, B-FR-15, B-FR-16, DL-043).

``POST /runs/{id}/scenarios`` makes a *derived* run: the same model, seed, instruments, start
prices, parameters and correlation as its parent (read from the parent, nothing from the market),
with a scenario applied on top. The parent is never changed. The derived run is stored like any run,
so it has its own statistics, quantiles, paths (when small) and median path, and its ticks are
served by the same read API with ``scenario`` set. A scenario is a row of data: a quant can add
one, or it can be inserted with SQL, and no code changes.
"""

import time
import uuid
from datetime import UTC, datetime
from typing import Any

import numpy as np
from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from qs_simulation.domain.runs import RunRefused, storage_mode
from qs_simulation.domain.scenarios import Scenario, parse, problems_of
from qs_simulation.domain.sharding import REQUIRED
from qs_simulation.models import (
    calibration,
    instrument_ref,
    job,
    run,
    run_correlation,
    run_instrument,
    scenario,
)
from qs_simulation.ports import RiskCalculator
from qs_simulation.runs import (
    NOT_FOUND,
    Computed,
    Progress,
    RunInstrument,
    fail_run,
    generate_run,
    log,
    store_run,
)
from qs_template import Database
from qs_template.errors import ServiceError
from qs_template.jobs import Handler, Job, JobQueue, ProgressReporter

KIND = "stress_run"
SCENARIO_NOT_FOUND = ServiceError(
    404,
    "Scenario not found",
    "No scenario has this code.",
    type_="urn:quantsim:problem:scenario-not-found",
)


def _invalid_params(problems: list[tuple[str, str]]) -> ServiceError:
    """A 422 that names each wrong parameter (B-FR-15)."""
    return ServiceError(
        422,
        "Invalid scenario parameters",
        "; ".join(f"{field}: {message}" for field, message in problems),
        type_="urn:quantsim:problem:invalid-scenario",
        extra={"errors": [{"field": f, "message": m} for f, m in problems]},
    )


def parse_checked(type_: str, params: dict[str, Any]) -> Scenario:
    try:
        return parse(type_, params)
    except ValidationError as error:
        raise _invalid_params(problems_of(error)) from error


class ScenarioService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list(self) -> list[dict[str, Any]]:
        rows = (await self._session.execute(select(scenario).order_by(scenario.c.code))).all()
        return [_row(r) for r in rows]

    async def create(
        self, code: str, name: str, type_: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        parse_checked(type_, params)  # the database repeats the bounds as CHECKs
        try:
            async with self._session.begin_nested():
                created = (
                    await self._session.execute(
                        scenario.insert()
                        .values(code=code, name=name, type=type_, params=params)
                        .returning(*scenario.c)
                    )
                ).one()
        except IntegrityError as error:
            raise ServiceError(
                409,
                "Scenario code already used",
                f"A scenario with the code {code!r} exists.",
                type_="urn:quantsim:problem:scenario-exists",
            ) from error
        return _row(created)


def _row(r: Any) -> dict[str, Any]:
    return {
        "id": r.id,
        "code": r.code,
        "name": r.name,
        "type": r.type,
        "params": r.params,
        "created_at": r.created_at,
    }


class StressService:
    def __init__(self, session: AsyncSession, queue: JobQueue) -> None:
        self._session = session
        self._queue = queue

    async def derive(
        self,
        parent_id: uuid.UUID,
        scenario_code: str,
        *,
        actor: uuid.UUID,
        idempotency_key: str | None,
    ) -> tuple[uuid.UUID, bool]:
        """Queue a stressed copy of a completed run; returns its id and whether it is new."""
        parent = (await self._session.execute(select(run).where(run.c.id == parent_id))).first()
        if parent is None:
            raise NOT_FOUND
        if parent.status != "completed":
            raise ServiceError(
                409,
                "The run is not complete",
                "A scenario is applied to the paths of a completed run.",
                type_="urn:quantsim:problem:run-not-complete",
            )
        chosen = (
            await self._session.execute(select(scenario).where(scenario.c.code == scenario_code))
        ).first()
        if chosen is None:
            raise SCENARIO_NOT_FOUND
        too_long = parse_checked(chosen.type, chosen.params).fits(parent.n_steps)
        if too_long:
            raise _invalid_params(too_long)
        payload = {
            "parent_run_id": str(parent_id),
            "scenario_id": str(chosen.id),
            "created_by": str(actor),
        }
        submitted = await self._queue.submit(
            self._session, KIND, payload, idempotency_key=idempotency_key
        )
        if not submitted.created:
            stored = (
                await self._session.execute(select(job.c.payload).where(job.c.id == submitted.id))
            ).scalar_one()
            if {k: v for k, v in stored.items() if k != "created_by"} != {
                k: v for k, v in payload.items() if k != "created_by"
            }:
                raise ServiceError(
                    409,
                    "Idempotency key already used",
                    "This key was used for a different request.",
                    type_="urn:quantsim:problem:idempotency-conflict",
                )
            return submitted.id, False
        members = (
            await self._session.execute(
                select(run_instrument.c.instrument_id).where(run_instrument.c.run_id == parent_id)
            )
        ).all()
        await self._session.execute(
            run.insert().values(
                id=submitted.id,
                model=parent.model,
                n_paths=parent.n_paths,
                n_steps=parent.n_steps,
                seed=parent.seed,
                idempotency_key=idempotency_key or f"stress:{submitted.id}",
                status="queued",
                storage_mode=storage_mode(parent.n_paths, parent.n_steps, len(members)),
                parent_run_id=parent_id,
                scenario_id=chosen.id,
                job_id=submitted.id,
                created_by=actor,
            )
        )
        return submitted.id, True


def make_handler(
    *, database: Database, risk: RiskCalculator, workers: int, max_attempts: int
) -> Handler:
    """The job function of kind ``stress_run``: it needs the database and nothing else, so it runs
    wherever a worker runs, with or without a market service."""

    async def handle(job_: Job, report: ProgressReporter) -> dict[str, Any]:
        run_id = job_.id
        began = time.perf_counter()
        async with database.transaction() as session:
            row = (
                await session.execute(select(run).where(run.c.id == run_id).with_for_update())
            ).first()
            if row is None:
                raise RuntimeError(f"run {run_id} has no row")
            if row.status == "completed":
                return {"status": "completed"}
            await session.execute(
                update(run)
                .where(run.c.id == run_id)
                .values(status="running", started_at=row.started_at or datetime.now(UTC))
            )
        progress = Progress(database, run_id, report)
        try:
            await progress.at(0.05)
            computed = await _compute(database, row, risk, workers, progress)
            await store_run(database, run_id, row, computed, risk)
        except RunRefused as refusal:
            await fail_run(database, run_id, refusal.code, refusal.reason)
            return {"status": "failed", "code": refusal.code, "reason": refusal.reason}
        except Exception as error:
            if job_.attempt >= max_attempts:
                await fail_run(database, run_id, "failed", str(error))
            raise
        log.info(
            "stressed run completed",
            run_id=str(run_id),
            parent_run_id=str(row.parent_run_id),
            instruments=len(computed.members),
            seconds=round(time.perf_counter() - began, 3),
        )
        return {"status": "completed", "median_path_index": computed.median_index}

    return handle


async def _compute(
    database: Database, row: Any, risk: RiskCalculator, workers: int, progress: Progress
) -> Computed:
    async with database.transaction() as session:
        members = (
            await session.execute(
                select(
                    run_instrument.c.instrument_id,
                    run_instrument.c.calibration_id,
                    run_instrument.c.s0,
                    calibration.c.params,
                    instrument_ref.c.symbol,
                )
                .select_from(
                    run_instrument.join(
                        calibration, calibration.c.id == run_instrument.c.calibration_id
                    ).outerjoin(
                        instrument_ref,
                        instrument_ref.c.instrument_id == run_instrument.c.instrument_id,
                    )
                )
                .where(run_instrument.c.run_id == row.parent_run_id)
                .order_by(run_instrument.c.position)
            )
        ).all()
        matrix = (
            await session.execute(
                select(run_correlation.c.matrix).where(
                    run_correlation.c.run_id == row.parent_run_id
                )
            )
        ).scalar_one()
        chosen = (
            await session.execute(select(scenario).where(scenario.c.id == row.scenario_id))
        ).one()
    overlay = parse_checked(chosen.type, chosen.params)
    await progress.at(0.15)
    return await generate_run(
        row,
        [RunInstrument(m.instrument_id, m.calibration_id) for m in members],
        [m.s0 for m in members],
        np.array(matrix, dtype=np.float64),
        {
            name: np.array([m.params[name] for m in members], dtype=np.float64)
            for name in REQUIRED[row.model]
        },
        [m.symbol or str(m.instrument_id) for m in members],
        risk,
        workers,
        progress,
        scenario=overlay,
    )
