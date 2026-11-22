"""Monte Carlo runs: submit, run the job, read, regenerate (B16, B-FR-11, B-FR-13, B-FR-14).

``submit`` validates and queues (K1) and answers at once. The job reads each instrument's start
price and the correlation matrix through ports, generates the paths in fixed shards (B10) and
computes the statistics and per-step quantiles. It picks the median path and writes everything (the
paths too when the run is small enough) in ONE transaction with the ``sim.completed`` event, so a
run is either complete and announced or not there at all. The run's id is its job's id.

A run is reproducible from what is stored: the seed, the model, the calibrated parameters, the start
prices (stored at the precision they were generated from) and the correlation matrix (stored before
repair, which is deterministic). ``regenerate`` builds the same paths again, bit for bit.
"""

import asyncio
import os
import secrets
import time
import uuid
from collections.abc import AsyncIterator, Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import numpy as np
from sqlalchemy import Table, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from qs_simulation.domain.correlation import Array, RepairRecord
from qs_simulation.domain.runs import (
    CORRELATION_UNAVAILABLE,
    INVALID_WINDOW,
    MAX_INSTRUMENTS,
    MIN_PATHS,
    NO_START_PRICE,
    PRICE_PLACES,
    InstrumentSummary,
    RunRefused,
    check_paths,
    median_path_index,
    run_values,
    step_quantiles,
    storage_mode,
    terminal_statistics,
)
from qs_simulation.domain.scenarios import Scenario, parse
from qs_simulation.domain.sharding import REQUIRED, PathRequest, generate
from qs_simulation.models import (
    MAX_PATHS,
    MAX_STEPS,
    calibration,
    instrument_ref,
    job,
    path_quantile,
    path_value,
    run,
    run_correlation,
    run_instrument,
    run_statistics,
    scenario,
)
from qs_simulation.ports import (
    CorrelationSource,
    InstrumentNotFound,
    PriceWindowSource,
    RiskCalculator,
)
from qs_template import Database
from qs_template.errors import ServiceError
from qs_template.events import EventEnvelope
from qs_template.jobs import Handler, Job, JobQueue, ProgressReporter
from qs_template.logging import get_logger
from qs_template.messaging import add_event

log = get_logger(__name__)

KIND = "monte_carlo"
INVALID_RUN = "urn:quantsim:problem:invalid-run"
RUN_TOO_LARGE = "urn:quantsim:problem:run-too-large"
NOT_FOUND = ServiceError(
    404,
    "Run not found",
    "No run has this id.",
    type_="urn:quantsim:problem:not-found",
)
START_PRICE_LOOKBACK = timedelta(days=15)  # a calibration may end on a holiday
PROGRESS_STEPS = 10  # an event for every tenth of the work
COPY_BATCH = 200_000


# ---- the request ----


@dataclass(frozen=True)
class RunInstrument:
    instrument_id: uuid.UUID
    calibration_id: uuid.UUID


@dataclass(frozen=True)
class RunRequest:
    model: str
    instruments: tuple[RunInstrument, ...]
    n_paths: int
    n_steps: int
    seed: int | None = None
    correlation_start: date | None = None
    correlation_end: date | None = None

    def config(self) -> dict[str, Any]:
        """What identifies the run apart from its seed: one key must always mean this."""
        return {
            "model": self.model,
            "instruments": [
                {"instrument_id": str(i.instrument_id), "calibration_id": str(i.calibration_id)}
                for i in self.instruments
            ],
            "n_paths": self.n_paths,
            "n_steps": self.n_steps,
            "correlation_start": _iso(self.correlation_start),
            "correlation_end": _iso(self.correlation_end),
        }


def _iso(value: date | None) -> str | None:
    return None if value is None else value.isoformat()


def shard_workers(configured: int, cpus: int | None = None) -> int:
    """Processes that generate shards: the configured number, or one core fewer than there are, so
    the API keeps a core (B-NFR-14); never fewer than one."""
    return configured or max(1, (cpus or os.cpu_count() or 2) - 1)


def _invalid(detail: str) -> ServiceError:
    return ServiceError(422, "The run cannot be made", detail, type_=INVALID_RUN)


# ---- the service the API uses ----


class RunService:
    def __init__(
        self,
        session: AsyncSession,
        queue: JobQueue,
        *,
        max_run_values: int,
        risk: RiskCalculator,
    ) -> None:
        self._session = session
        self._queue = queue
        self._max_values = max_run_values
        self._risk = risk

    async def _check(self, request: RunRequest) -> None:
        count = len(request.instruments)
        if not MIN_PATHS <= request.n_paths <= MAX_PATHS:
            raise _invalid(f"n_paths must be between {MIN_PATHS} and {MAX_PATHS}")
        if not 1 <= request.n_steps <= MAX_STEPS:
            raise _invalid(f"n_steps must be between 1 and {MAX_STEPS}")
        if not 1 <= count <= MAX_INSTRUMENTS:
            raise _invalid(f"a run takes between 1 and {MAX_INSTRUMENTS} instruments")
        ids = [i.instrument_id for i in request.instruments]
        if len(set(ids)) != count:
            raise _invalid("an instrument appears twice")
        if request.seed is not None and not 0 <= request.seed < 2**63:
            raise _invalid("seed must be between 0 and 2^63 - 1")
        if (request.correlation_start is None) != (request.correlation_end is None):
            raise _invalid("give both ends of the correlation window, or neither")
        if request.correlation_start and request.correlation_end:
            if request.correlation_start >= request.correlation_end:
                raise _invalid("the correlation window must start before it ends")
        if run_values(request.n_paths, request.n_steps, count) > self._max_values:
            raise ServiceError(
                422,
                "The run is too large",
                f"{request.n_paths} paths x {request.n_steps} steps x {count} instruments is more "
                f"than the {self._max_values:,} prices this deployment generates at once.",
                type_=RUN_TOO_LARGE,
            )
        found = {
            row.id: row
            for row in (
                await self._session.execute(
                    select(calibration).where(
                        calibration.c.id.in_([i.calibration_id for i in request.instruments])
                    )
                )
            ).all()
        }
        problems: list[str] = []
        for item in request.instruments:
            row = found.get(item.calibration_id)
            if row is None:
                problems.append(f"calibration {item.calibration_id} does not exist")
            elif row.instrument_id != item.instrument_id:
                problems.append(
                    f"calibration {item.calibration_id} is of another instrument than "
                    f"{item.instrument_id}"
                )
            elif row.model != request.model:
                problems.append(
                    f"calibration {item.calibration_id} is a {row.model} fit, the run is "
                    f"{request.model}"
                )
            elif not row.converged:
                problems.append(f"calibration {item.calibration_id} did not converge")
        if problems:
            raise _invalid("; ".join(problems))

    async def submit(
        self, request: RunRequest, *, actor: uuid.UUID, idempotency_key: str | None
    ) -> tuple[uuid.UUID, bool]:
        """Queue a run; the same idempotency key returns the run that already exists (409 when it
        was asked for something else). Returns the run id and whether it was newly queued."""
        await self._check(request)
        seed = request.seed if request.seed is not None else secrets.randbits(63)
        payload = {**request.config(), "seed": seed, "created_by": str(actor)}
        submitted = await self._queue.submit(
            self._session, KIND, payload, idempotency_key=idempotency_key
        )
        if not submitted.created:
            stored = (
                await self._session.execute(select(job.c.payload).where(job.c.id == submitted.id))
            ).scalar_one()
            same = {k: v for k, v in stored.items() if k not in ("seed", "created_by")}
            if same != request.config() or (
                request.seed is not None and stored["seed"] != request.seed
            ):
                raise ServiceError(
                    409,
                    "Idempotency key already used",
                    "This key was used for a different run.",
                    type_="urn:quantsim:problem:idempotency-conflict",
                )
            return submitted.id, False
        await self._session.execute(
            run.insert().values(
                id=submitted.id,
                model=request.model,
                n_paths=request.n_paths,
                n_steps=request.n_steps,
                seed=seed,
                idempotency_key=idempotency_key or f"run:{submitted.id}",
                status="queued",
                storage_mode=storage_mode(
                    request.n_paths, request.n_steps, len(request.instruments)
                ),
                job_id=submitted.id,
                created_by=actor,
            )
        )
        return submitted.id, True

    async def describe(self, run_id: uuid.UUID) -> dict[str, Any]:
        """The run in the shape the API serves: its state, progress and statistics."""
        row = (
            await self._session.execute(
                select(run, scenario.c.code.label("scenario_code"))
                .select_from(run.outerjoin(scenario, scenario.c.id == run.c.scenario_id))
                .where(run.c.id == run_id)
            )
        ).first()
        if row is None:
            raise NOT_FOUND
        state = await self._queue.get(self._session, run_id)
        status, error = row.status, row.error
        if status in ("queued", "running") and state is not None and state.status == "failed":
            status, error = "failed", state.error  # the queue gave up before the job could say so
        stored = (
            await self._session.execute(
                select(run_instrument.c.instrument_id, instrument_ref.c.symbol)
                .select_from(
                    run_instrument.outerjoin(
                        instrument_ref,
                        instrument_ref.c.instrument_id == run_instrument.c.instrument_id,
                    )
                )
                .where(run_instrument.c.run_id == run_id)
                .order_by(run_instrument.c.position)
            )
        ).all()
        if stored:
            symbols = [r.symbol for r in stored]
        else:  # not generated yet: the instruments are in the job's request
            wanted = [uuid.UUID(i["instrument_id"]) for i in await self._requested(run_id)]
            names = dict(
                (
                    await self._session.execute(
                        select(instrument_ref.c.instrument_id, instrument_ref.c.symbol).where(
                            instrument_ref.c.instrument_id.in_(wanted)
                        )
                    )
                ).all()
            )
            symbols = [names.get(i, str(i)) for i in wanted]
        statistics = (
            await self._session.execute(
                select(run_statistics, instrument_ref.c.symbol)
                .select_from(
                    run_statistics.outerjoin(
                        instrument_ref,
                        instrument_ref.c.instrument_id == run_statistics.c.instrument_id,
                    ).join(
                        run_instrument,
                        (run_instrument.c.run_id == run_statistics.c.run_id)
                        & (run_instrument.c.instrument_id == run_statistics.c.instrument_id),
                    )
                )
                .where(run_statistics.c.run_id == run_id)
                .order_by(run_instrument.c.position)
            )
        ).all()
        return {
            "id": run_id,
            "status": status,
            "model": row.model,
            "n_paths": row.n_paths,
            "n_steps": row.n_steps,
            "symbols": symbols,
            "median_path_index": row.median_path_index,
            "parent_run_id": row.parent_run_id,
            "scenario": row.scenario_code,
            "created_at": row.created_at,
            "progress": 1.0 if status == "completed" else (state.progress if state else 0.0),
            "seed": row.seed,
            "storage_mode": row.storage_mode,
            "statistics": [
                {
                    "instrument_id": s.instrument_id,
                    "symbol": s.symbol,
                    "mean_price": format(s.mean_price, "f"),
                    "median_price": format(s.median_price, "f"),
                    "p5_price": format(s.p5_price, "f"),
                    "p95_price": format(s.p95_price, "f"),
                    "var95": format(s.var95, "f"),
                    "cvar95": format(s.cvar95, "f"),
                }
                for s in statistics
            ],
            "error": error,
        }

    async def _requested(self, run_id: uuid.UUID) -> list[dict[str, str]]:
        payload = (
            await self._session.execute(select(job.c.payload).where(job.c.id == run_id))
        ).scalar_one()
        instruments: list[dict[str, str]] = payload["instruments"]
        return instruments


# ---- regenerating a stored run ----


async def load_request(session: AsyncSession, run_id: uuid.UUID) -> tuple[Any, PathRequest]:
    """The run's row and everything that defines its paths, read from what is stored."""
    row = (await session.execute(select(run).where(run.c.id == run_id))).first()
    if row is None:
        raise NOT_FOUND
    if row.status != "completed":
        raise ServiceError(
            409,
            "The run is not complete",
            "Paths exist once the run has completed.",
            type_="urn:quantsim:problem:run-not-complete",
        )
    members = (
        await session.execute(
            select(run_instrument.c.s0, calibration.c.params)
            .select_from(
                run_instrument.join(
                    calibration, calibration.c.id == run_instrument.c.calibration_id
                )
            )
            .where(run_instrument.c.run_id == run_id)
            .order_by(run_instrument.c.position)
        )
    ).all()
    matrix = (
        await session.execute(
            select(run_correlation.c.matrix).where(run_correlation.c.run_id == run_id)
        )
    ).scalar_one()
    overlay: Scenario | None = None
    if row.scenario_id is not None:  # a stressed run: the parent's inputs with the scenario on top
        found = (
            await session.execute(
                select(scenario.c.type, scenario.c.params).where(scenario.c.id == row.scenario_id)
            )
        ).one()
        overlay = parse(found.type, found.params)
    request = PathRequest(
        model=row.model,
        s0=np.array([float(m.s0) for m in members], dtype=np.float64),
        params={
            name: np.array([m.params[name] for m in members], dtype=np.float64)
            for name in REQUIRED[row.model]
        },
        correlation=np.array(matrix, dtype=np.float64),
        n_paths=row.n_paths,
        n_steps=row.n_steps,
        seed=row.seed,
        scenario=overlay,
    )
    return row, request


async def regenerate(session: AsyncSession, run_id: uuid.UUID) -> tuple[Array, RepairRecord]:
    """The run's paths again, from what is stored: bit for bit what the job generated."""
    _, request = await load_request(session, run_id)
    return await asyncio.to_thread(generate, request, 1)


# ---- the job ----


@dataclass(frozen=True)
class Computed:
    """Everything the job works out before it writes anything."""

    members: list[tuple[RunInstrument, Decimal, int]]  # instrument, start price, position
    matrix: Array
    record: RepairRecord
    summaries: list[InstrumentSummary]
    quantiles: Array  # (steps, instruments, 7)
    paths: Array | None  # kept only when the run is stored in full
    median_index: int
    symbols: list[str]


class Progress:
    """K1's progress, plus a ``sim.progress`` event for every tenth of the work."""

    def __init__(self, database: Database, run_id: uuid.UUID, report: ProgressReporter) -> None:
        self._database = database
        self._run_id = run_id
        self._report = report
        self._tenth = -1

    async def at(self, fraction: float) -> None:
        await self._report(fraction)
        tenth = int(fraction * PROGRESS_STEPS)
        if tenth > self._tenth:
            self._tenth = tenth
            async with self._database.transaction() as session:
                await add_event(
                    session,
                    EventEnvelope(
                        event_type="sim.progress",
                        producer="simulation",
                        aggregate_type="run",
                        aggregate_id=str(self._run_id),
                        data={"run_id": str(self._run_id), "progress": round(fraction, 4)},
                    ),
                )


def _event(run_id: uuid.UUID, kind: str, data: dict[str, Any]) -> EventEnvelope:
    return EventEnvelope(
        event_type=kind,
        producer="simulation",
        aggregate_type="run",
        aggregate_id=str(run_id),
        data={"run_id": str(run_id), **data},
    )


async def _start_price(source: PriceWindowSource, instrument_id: uuid.UUID, end: date) -> Decimal:
    points = await source.window(instrument_id, end - START_PRICE_LOOKBACK, end)
    if not points:
        raise RunRefused(
            NO_START_PRICE, f"instrument {instrument_id} has no close in the 15 days to {end}"
        )
    last = max(points, key=lambda p: p.session_date)
    price = last.adj_close.quantize(Decimal(1).scaleb(-PRICE_PLACES))
    if price <= 0:
        raise RunRefused(NO_START_PRICE, f"the start price of {instrument_id} is not positive")
    return price


def _matrix_refusal(symbols: Sequence[str], values: Array, unavailable: Sequence[Any]) -> None:
    """DL-012: a correlation that was not computed is never invented."""
    if unavailable:
        row, column, reason = unavailable[0]
        more = f" (and {len(unavailable) - 1} more)" if len(unavailable) > 1 else ""
        raise RunRefused(
            CORRELATION_UNAVAILABLE,
            f"the correlation of {row} and {column} is undefined: {reason}{more}",
        )
    if not np.all(np.isfinite(values)):
        raise RunRefused(CORRELATION_UNAVAILABLE, "the correlation matrix has undefined cells")


def make_handler(
    *,
    database: Database,
    prices: PriceWindowSource,
    correlations: CorrelationSource,
    risk: RiskCalculator,
    workers: int,
    max_attempts: int,
) -> Handler:
    """The job function of kind ``monte_carlo``. A refusal marks the run failed with its reason and
    is not retried; any other failure is retried by the queue, and on the last attempt the run is
    marked failed with the error before it is raised."""

    async def handle(job_: Job, report: ProgressReporter) -> dict[str, Any]:
        run_id = job_.id
        began = time.perf_counter()
        async with database.transaction() as session:
            row = (
                await session.execute(select(run).where(run.c.id == run_id).with_for_update())
            ).first()
            if row is None:
                raise RuntimeError(f"run {run_id} has no row")
            if row.status == "completed":  # the queue ran it again after the result was recorded
                return {"status": "completed"}
            await session.execute(
                update(run)
                .where(run.c.id == run_id)
                .values(status="running", started_at=row.started_at or datetime.now(UTC))
            )
        progress = Progress(database, run_id, report)
        try:
            await progress.at(0.05)
            computed = await _compute(
                database, job_.payload, row, prices, correlations, risk, workers, progress
            )
            await store_run(database, run_id, row, computed, risk)
        except RunRefused as refusal:
            await fail_run(database, run_id, refusal.code, refusal.reason)
            return {"status": "failed", "code": refusal.code, "reason": refusal.reason}
        except InstrumentNotFound:
            reason = "the market service has no such instrument"
            await fail_run(database, run_id, "instrument_not_found", reason)
            return {"status": "failed", "code": "instrument_not_found", "reason": reason}
        except Exception as error:
            if job_.attempt >= max_attempts:
                await fail_run(database, run_id, "failed", str(error))
            raise
        log.info(
            "run completed",
            run_id=str(run_id),
            model=row.model,
            n_paths=row.n_paths,
            n_steps=row.n_steps,
            instruments=len(computed.members),
            storage_mode=row.storage_mode,
            seconds=round(time.perf_counter() - began, 3),
            risk=risk.version,
        )
        return {"status": "completed", "median_path_index": computed.median_index}

    return handle


async def _compute(
    database: Database,
    payload: dict[str, Any],
    row: Any,
    prices: PriceWindowSource,
    correlations: CorrelationSource,
    risk: RiskCalculator,
    workers: int,
    progress: Progress,
) -> Computed:
    members = [
        RunInstrument(uuid.UUID(i["instrument_id"]), uuid.UUID(i["calibration_id"]))
        for i in payload["instruments"]
    ]
    async with database.transaction() as session:
        fits = {
            r.id: r
            for r in (
                await session.execute(
                    select(calibration).where(
                        calibration.c.id.in_([m.calibration_id for m in members])
                    )
                )
            ).all()
        }
        names = dict(
            (
                await session.execute(
                    select(instrument_ref.c.instrument_id, instrument_ref.c.symbol).where(
                        instrument_ref.c.instrument_id.in_([m.instrument_id for m in members])
                    )
                )
            ).all()
        )
    s0 = [
        await _start_price(prices, m.instrument_id, fits[m.calibration_id].window_end)
        for m in members
    ]
    await progress.at(0.1)
    start, end = payload["correlation_start"], payload["correlation_end"]
    if start is None:
        start = max(fits[m.calibration_id].window_start for m in members)
        end = min(fits[m.calibration_id].window_end for m in members)
    else:
        start, end = date.fromisoformat(start), date.fromisoformat(end)
    symbols = [names.get(m.instrument_id, str(m.instrument_id)) for m in members]
    if len(members) == 1:
        matrix = np.ones((1, 1), dtype=np.float64)
    else:
        if start >= end:
            raise RunRefused(INVALID_WINDOW, "the calibration windows do not overlap")
        found = await correlations.matrix([m.instrument_id for m in members], start, end)
        _matrix_refusal(symbols, np.asarray(found.values), found.unavailable)
        matrix = np.asarray(found.values, dtype=np.float64)
    await progress.at(0.15)
    params = {
        name: np.array([fits[m.calibration_id].params[name] for m in members], dtype=np.float64)
        for name in REQUIRED[row.model]
    }
    return await generate_run(
        row, members, s0, matrix, params, symbols, risk, workers, progress, scenario=None
    )


async def generate_run(
    row: Any,
    members: Sequence[RunInstrument],
    s0: Sequence[Decimal],
    matrix: Array,
    params: dict[str, Array],
    symbols: list[str],
    risk: RiskCalculator,
    workers: int,
    progress: Progress,
    *,
    scenario: Scenario | None,
) -> Computed:
    """The paths of a run and everything computed from them: shared by the base run (its inputs
    come from the market) and the stressed run (its inputs come from its parent)."""
    request = PathRequest(
        model=row.model,
        s0=np.array([float(p) for p in s0], dtype=np.float64),
        params=params,
        correlation=matrix,
        n_paths=row.n_paths,
        n_steps=row.n_steps,
        seed=row.seed,
        scenario=scenario,
    )
    loop = asyncio.get_running_loop()

    def on_shard(done: int, total: int) -> None:
        asyncio.run_coroutine_threadsafe(progress.at(0.15 + 0.6 * done / total), loop).result()

    def work() -> tuple[Array, RepairRecord]:
        return generate(request, workers, on_shard)

    try:
        paths, record = await asyncio.to_thread(work)
    except ValueError as error:  # a matrix the generator cannot take (not symmetric, off [-1, 1])
        raise RunRefused("invalid_correlation", str(error)) from error
    check_paths(paths)
    await progress.at(0.8)
    summaries = terminal_statistics(paths, request.s0, risk)
    quantiles = step_quantiles(paths)
    median = median_path_index(paths, request.s0)
    await progress.at(0.9)
    return Computed(
        members=[(m, s0[i], i) for i, m in enumerate(members)],
        matrix=matrix,
        record=record,
        summaries=summaries,
        quantiles=quantiles,
        paths=paths if row.storage_mode == "full" else None,
        median_index=median,
        symbols=symbols,
    )


async def _copy(session: AsyncSession, table: Table, lines: Iterator[str]) -> None:
    """Bulk write with COPY (CSV) on the session's own connection, so it is part of its transaction.
    Rows are text lines, so a price is formatted once, to ten places, and PostgreSQL reads it back
    as the same NUMERIC: no Python decimal is built per value, which is what makes 1.26 million rows
    take seconds. The lines are produced a chunk at a time."""

    async def source() -> AsyncIterator[bytes]:
        chunk: list[str] = []
        for line in lines:
            chunk.append(line)
            if len(chunk) >= COPY_BATCH:
                yield ("\n".join(chunk) + "\n").encode()
                chunk = []
        if chunk:
            yield ("\n".join(chunk) + "\n").encode()

    connection = await session.connection()
    raw = await connection.get_raw_connection()
    await raw.driver_connection.copy_to_table(  # type: ignore[union-attr]
        table.name, source=source(), columns=[c.name for c in table.columns], format="csv"
    )


def _quantile_lines(run_id: uuid.UUID, computed: Computed) -> Iterator[str]:
    for member, _, position in computed.members:
        prefix = f"{run_id},{member.instrument_id},"
        for step in range(computed.quantiles.shape[0]):
            values = ",".join(f"{q:.{PRICE_PLACES}f}" for q in computed.quantiles[step, position])
            yield f"{prefix}{step + 1},{values}"


def _path_lines(run_id: uuid.UUID, computed: Computed) -> Iterator[str]:
    assert computed.paths is not None
    for member, _, position in computed.members:
        for path in range(computed.paths.shape[0]):
            prefix = f"{run_id},{member.instrument_id},{path},"
            series = computed.paths[path, :, position].tolist()
            for step, price in enumerate(series, start=1):
                yield f"{prefix}{step},{price:.{PRICE_PLACES}f}"


async def store_run(
    database: Database, run_id: uuid.UUID, row: Any, computed: Computed, risk: RiskCalculator
) -> None:
    """Everything the run produced, and the event that announces it, in one transaction."""
    async with database.transaction() as session:
        current = (
            await session.execute(select(run.c.status).where(run.c.id == run_id).with_for_update())
        ).scalar_one()
        if current == "completed":
            return
        await session.execute(
            run_instrument.insert(),
            [
                {
                    "run_id": run_id,
                    "instrument_id": m.instrument_id,
                    "calibration_id": m.calibration_id,
                    "position": position,
                    "s0": s0,
                }
                for m, s0, position in computed.members
            ],
        )
        await session.execute(
            run_correlation.insert().values(
                run_id=run_id,
                size=len(computed.members),
                matrix=computed.matrix.tolist(),
                repair_applied=computed.record.applied,
                min_eigenvalue_before=Decimal(repr(computed.record.min_eigenvalue_before)),
                frobenius_change=Decimal(repr(computed.record.frobenius_change)),
            )
        )
        await session.execute(
            run_statistics.insert(),
            [
                {
                    "run_id": run_id,
                    "instrument_id": m.instrument_id,
                    "mean_price": s.mean_price,
                    "median_price": s.median_price,
                    "p5_price": s.p5_price,
                    "p95_price": s.p95_price,
                    "var95": s.var95,
                    "cvar95": s.cvar95,
                }
                for (m, _, _), s in zip(computed.members, computed.summaries, strict=True)
            ],
        )
        await _copy(session, path_quantile, _quantile_lines(run_id, computed))
        if computed.paths is not None:
            await _copy(session, path_value, _path_lines(run_id, computed))
        await session.execute(
            update(run)
            .where(run.c.id == run_id)
            .values(
                status="completed",
                median_path_index=computed.median_index,
                finished_at=datetime.now(UTC),
                error=None,
            )
        )
        await add_event(
            session,
            _event(
                run_id,
                "sim.completed",
                {
                    "model": row.model,
                    "n_paths": row.n_paths,
                    "n_steps": row.n_steps,
                    "seed": row.seed,
                    "storage_mode": row.storage_mode,
                    "median_path_index": computed.median_index,
                    "symbols": computed.symbols,
                    "repair_applied": computed.record.applied,
                    "risk": risk.version,
                    "parent_run_id": None if row.parent_run_id is None else str(row.parent_run_id),
                },
            ),
        )


async def fail_run(database: Database, run_id: uuid.UUID, code: str, reason: str) -> None:
    async with database.transaction() as session:
        updated = await session.execute(
            update(run)
            .where(run.c.id == run_id, run.c.status != "completed")
            .values(
                status="failed", error=f"{code}: {reason}"[:4000], finished_at=datetime.now(UTC)
            )
            .returning(run.c.id)
        )
        if updated.first() is not None:
            await add_event(session, _event(run_id, "sim.failed", {"code": code, "reason": reason}))


__all__ = ["KIND", "RunInstrument", "RunRequest", "RunService", "make_handler", "regenerate"]
