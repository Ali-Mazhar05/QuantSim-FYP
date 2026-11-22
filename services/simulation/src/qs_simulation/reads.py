"""The read side of the simulation service (B18): the lists, the quantiles and the path tick feed.

Nothing here writes. A run's ticks come from the stored paths when the run kept them (storage mode
``full``) and are generated again from the seed when it kept quantiles only (DL-013); both give the
same text, because a stored price was written with the same formatting as a regenerated one
(``price_text``) from the same float (DL-039). Only the shard holding the requested path is
generated, so a page costs one shard, not the whole run.
"""

import asyncio
import json
import uuid
from typing import Any

import xxhash
from sqlalchemy import Select, and_, case, exists, select, tuple_
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.expression import ColumnElement, cast

from qs_simulation.calibrations import fit_row
from qs_simulation.domain.calendar import step_closes
from qs_simulation.domain.runs import PRICE_PLACES
from qs_simulation.domain.sharding import SHARD_SIZE, generate_shard
from qs_simulation.models import (
    calibration,
    instrument_ref,
    job,
    path_quantile,
    path_value,
    run,
    run_correlation,
    run_instrument,
    scenario,
)
from qs_simulation.paging import decode_cursor, encode_cursor
from qs_simulation.runs import NOT_FOUND, load_request
from qs_template.errors import ServiceError

# Changes whenever the generators or the formatting would give other prices for the same stored
# request; part of every tick's source fingerprint, so a consumer can tell.
GENERATOR_VERSION = "gen-1"
NOT_FOUND_TYPE = "urn:quantsim:problem:not-found"
VOLUME = "0.00000000"
LEVELS = ("q01", "q05", "q25", "q50", "q75", "q95", "q99")


def price_text(value: float) -> str:
    """A generated price as it is stored and served: ten decimals."""
    return f"{value:.{PRICE_PLACES}f}"


def require_path(path: int, n_paths: int) -> None:
    """A path outside the run (``path >= n_paths``) is 404, like an unknown run."""
    if path >= n_paths:
        raise ServiceError(
            404,
            "Path not found",
            f"This run has {n_paths} paths, numbered 0 to {n_paths - 1}; there is no path {path}.",
            type_=NOT_FOUND_TYPE,
        )


def _not_complete() -> ServiceError:
    return ServiceError(
        409,
        "The run is not complete",
        "Paths and quantiles exist once the run has completed.",
        type_="urn:quantsim:problem:run-not-complete",
    )


class Reads:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ---- calibrations ----

    async def calibrations(
        self,
        *,
        instrument: uuid.UUID | None,
        model: str | None,
        converged: bool | None,
        limit: int,
        cursor: str | None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        """The stored calibrations, newest first. A queued or refused one is not listed: it has no
        fit to choose; its id (the job id) is read with ``GET /calibrations/{id}``."""
        query = select(calibration, instrument_ref.c.symbol).select_from(
            calibration.outerjoin(
                instrument_ref, instrument_ref.c.instrument_id == calibration.c.instrument_id
            )
        )
        if instrument is not None:
            query = query.where(calibration.c.instrument_id == instrument)
        if model is not None:
            query = query.where(calibration.c.model == model)
        if converged is not None:
            query = query.where(calibration.c.converged == converged)
        rows, next_cursor = await self._page(
            query, calibration.c.created_at, calibration.c.id, limit, cursor
        )
        items = [
            {
                "id": r.id,
                "status": "succeeded",
                "progress": 1.0,
                "created_at": r.created_at,
                "finished_at": r.created_at,
                "calibration": fit_row(r),
                "refusal": None,
                "error": None,
            }
            for r in rows
        ]
        return items, next_cursor

    # ---- runs ----

    async def runs(
        self,
        *,
        status: str | None,
        instrument: uuid.UUID | None,
        limit: int,
        cursor: str | None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        """Runs newest first. The status is the one ``GET /runs/{id}`` shows: a run whose job the
        queue gave up on is ``failed`` even if the run row never learned it."""
        effective = _effective_status()
        query = select(
            run,
            scenario.c.code.label("scenario_code"),
            effective.label("effective_status"),
            job.c.payload,
        ).select_from(
            run.outerjoin(scenario, scenario.c.id == run.c.scenario_id).outerjoin(
                job, job.c.id == run.c.id
            )
        )
        if status is not None:
            query = query.where(effective == status)
        if instrument is not None:
            requested = cast(job.c.payload["instruments"], JSONB).contains(
                [{"instrument_id": str(instrument)}]
            )
            stored = exists().where(
                and_(
                    run_instrument.c.run_id == run.c.id,
                    run_instrument.c.instrument_id == instrument,
                )
            )
            query = query.where(stored | requested)
        rows, next_cursor = await self._page(query, run.c.created_at, run.c.id, limit, cursor)
        symbols = await self._symbols(rows)
        items = [
            {
                "id": r.id,
                "status": r.effective_status,
                "model": r.model,
                "n_paths": r.n_paths,
                "n_steps": r.n_steps,
                "symbols": symbols[r.id],
                "median_path_index": r.median_path_index,
                "parent_run_id": r.parent_run_id,
                "scenario": r.scenario_code,
                "created_at": r.created_at,
            }
            for r in rows
        ]
        return items, next_cursor

    async def _symbols(self, rows: list[Any]) -> dict[uuid.UUID, list[str]]:
        """The symbols of each run in the page: stored ones in matrix order; a stressed run not yet
        generated takes its parent's; else the ones requested."""
        parents = {r.id: r.parent_run_id for r in rows if r.parent_run_id is not None}
        lookup = list({*(r.id for r in rows), *parents.values()})
        stored_symbols: dict[uuid.UUID, list[str]] = {}
        if lookup:
            stored = await self._session.execute(
                select(
                    run_instrument.c.run_id, run_instrument.c.instrument_id, instrument_ref.c.symbol
                )
                .select_from(
                    run_instrument.outerjoin(
                        instrument_ref,
                        instrument_ref.c.instrument_id == run_instrument.c.instrument_id,
                    )
                )
                .where(run_instrument.c.run_id.in_(lookup))
                .order_by(run_instrument.c.run_id, run_instrument.c.position)
            )
            for run_id, instrument_id, symbol in stored.all():
                stored_symbols.setdefault(run_id, []).append(symbol or str(instrument_id))
        found = {
            r.id: stored_symbols.get(r.id) or stored_symbols.get(parents.get(r.id), [])  # type: ignore[arg-type]
            for r in rows
        }
        wanted = {
            r.id: [uuid.UUID(i["instrument_id"]) for i in (r.payload or {}).get("instruments", [])]
            for r in rows
            if not found[r.id]
        }
        if wanted:
            names = dict(
                (
                    await self._session.execute(
                        select(instrument_ref.c.instrument_id, instrument_ref.c.symbol).where(
                            instrument_ref.c.instrument_id.in_(
                                {i for v in wanted.values() for i in v}
                            )
                        )
                    )
                ).all()
            )
            for run_id, instrument_ids in wanted.items():
                found[run_id] = [names.get(i, str(i)) for i in instrument_ids]
        return found

    async def _page(
        self,
        query: Select[Any],
        created_at: ColumnElement[Any],
        row_id: ColumnElement[Any],
        limit: int,
        cursor: str | None,
    ) -> tuple[list[Any], str | None]:
        """Keyset paging, newest first: no page repeats or skips a row that arrives meanwhile."""
        if cursor is not None:
            last_at, last_id = decode_cursor(cursor)
            query = query.where(tuple_(created_at, row_id) < tuple_(last_at, last_id))
        rows = list(
            (
                await self._session.execute(
                    query.order_by(created_at.desc(), row_id.desc()).limit(limit + 1)
                )
            ).all()
        )
        if len(rows) <= limit:
            return rows, None
        rows = rows[:limit]
        return rows, encode_cursor(rows[-1].created_at, rows[-1].id)

    # ---- one run ----

    async def _completed(self, run_id: uuid.UUID) -> Any:
        row = (
            await self._session.execute(
                select(
                    run,
                    scenario.c.code.label("scenario_code"),
                    scenario.c.type.label("scenario_type"),
                    scenario.c.params.label("scenario_params"),
                )
                .select_from(run.outerjoin(scenario, scenario.c.id == run.c.scenario_id))
                .where(run.c.id == run_id)
            )
        ).first()
        if row is None:
            raise NOT_FOUND
        if row.status != "completed":
            raise _not_complete()
        return row

    async def _members(self, run_id: uuid.UUID) -> list[Any]:
        return list(
            (
                await self._session.execute(
                    select(
                        run_instrument.c.instrument_id,
                        run_instrument.c.position,
                        run_instrument.c.s0,
                        instrument_ref.c.symbol,
                        calibration.c.params,
                        calibration.c.qs_quant_version,
                        calibration.c.window_end,
                    )
                    .select_from(
                        run_instrument.join(
                            calibration, calibration.c.id == run_instrument.c.calibration_id
                        ).outerjoin(
                            instrument_ref,
                            instrument_ref.c.instrument_id == run_instrument.c.instrument_id,
                        )
                    )
                    .where(run_instrument.c.run_id == run_id)
                    .order_by(run_instrument.c.position)
                )
            ).all()
        )

    async def quantiles(self, run_id: uuid.UUID, instrument: uuid.UUID | None) -> dict[str, Any]:
        """The per-step quantiles of every instrument (or one) of a completed run."""
        row = await self._completed(run_id)
        members = await self._members(run_id)
        if instrument is not None:
            members = [m for m in members if m.instrument_id == instrument]
            if not members:
                raise ServiceError(
                    404,
                    "Instrument not in this run",
                    "The run does not include this instrument.",
                    type_=NOT_FOUND_TYPE,
                )
        steps = (
            await self._session.execute(
                select(path_quantile)
                .where(
                    path_quantile.c.run_id == run_id,
                    path_quantile.c.instrument_id.in_([m.instrument_id for m in members]),
                )
                .order_by(path_quantile.c.instrument_id, path_quantile.c.step)
            )
        ).all()
        by_instrument: dict[uuid.UUID, list[dict[str, Any]]] = {
            m.instrument_id: [] for m in members
        }
        for q in steps:
            by_instrument[q.instrument_id].append(
                {"step": q.step, **{level: format(getattr(q, level), "f") for level in LEVELS}}
            )
        return {
            "run_id": run_id,
            "n_steps": row.n_steps,
            "levels": {
                "q01": "0.01",
                "q05": "0.05",
                "q25": "0.25",
                "q50": "0.50",
                "q75": "0.75",
                "q95": "0.95",
                "q99": "0.99",
            },
            "instruments": [
                {
                    "instrument_id": m.instrument_id,
                    "symbol": m.symbol or str(m.instrument_id),
                    "start_price": format(m.s0, "f"),
                    "steps": by_instrument[m.instrument_id],
                }
                for m in members
            ],
        }

    # ---- the tick feed ----

    async def fingerprint(self, row: Any, members: list[Any]) -> str:
        """Identifies the run: its configuration and seed, each instrument's start price,
        parameters and the library that fitted them, the correlation as stored, and the generator
        version (the code). The same run always has the same fingerprint (xxh3, 128 bits)."""
        matrix = (
            await self._session.execute(
                select(run_correlation.c.matrix).where(run_correlation.c.run_id == row.id)
            )
        ).scalar_one()
        parts = [
            GENERATOR_VERSION,
            str(row.id),
            row.model,
            f"seed={row.seed}",
            f"paths={row.n_paths}",
            f"steps={row.n_steps}",
            f"scenario={row.scenario_code or '-'}:{row.scenario_type}:"
            f"{json.dumps(row.scenario_params, sort_keys=True)}",
            json.dumps(matrix, separators=(",", ":")),
            *(
                f"{m.instrument_id}:{m.s0}:{json.dumps(m.params, sort_keys=True)}"
                f":{m.qs_quant_version}"
                for m in members
            ),
        ]
        return "xxh3:" + xxhash.xxh3_128_hexdigest("|".join(parts).encode())

    async def ticks(
        self, run_id: uuid.UUID, path: int, after_seq: int, limit: int
    ) -> tuple[list[dict[str, Any]], int | None, str]:
        """One page of one path as ``market.tick.v1`` ticks, ordered by (step, symbol)."""
        row = await self._completed(run_id)
        require_path(path, row.n_paths)
        members = await self._members(run_id)
        fingerprint = await self.fingerprint(row, members)
        order = sorted(members, key=lambda m: m.symbol or str(m.instrument_id))
        width = len(order)
        total = row.n_steps * width
        if after_seq >= total:
            return [], None, fingerprint
        end = min(after_seq + limit, total)
        first_step, last_step = after_seq // width, (end - 1) // width
        prices = await self._prices(row, members, path, first_step, last_step)
        closes = step_closes(max(m.window_end for m in members), row.n_steps)
        items: list[dict[str, Any]] = []
        for offset in range(after_seq, end):
            step, k = divmod(offset, width)
            member = order[k]
            price = prices[step][member.position]
            items.append(
                {
                    "env_id": run_id,
                    "env_type": "synthetic",
                    "source_fingerprint": fingerprint,
                    "seq": offset + 1,
                    "session": step,
                    "session_date": None,
                    "ts": closes[step],
                    "instrument_id": member.instrument_id,
                    "symbol": member.symbol or str(member.instrument_id),
                    "open": price,
                    "high": price,
                    "low": price,
                    "close": price,
                    "volume": VOLUME,
                    "path_index": path,
                    "scenario": row.scenario_code,
                }
            )
        return items, (end if end < total else None), fingerprint

    async def _prices(
        self, row: Any, members: list[Any], path: int, first_step: int, last_step: int
    ) -> dict[int, dict[int, str]]:
        """Price text by step (from 0) and instrument position, for the steps asked."""
        grid: dict[int, dict[int, str]] = {s: {} for s in range(first_step, last_step + 1)}
        if row.storage_mode == "full":
            position = {m.instrument_id: m.position for m in members}
            stored = await self._session.execute(
                select(path_value.c.instrument_id, path_value.c.step, path_value.c.price).where(
                    path_value.c.run_id == row.id,
                    path_value.c.path_index == path,
                    path_value.c.step.between(first_step + 1, last_step + 1),
                )
            )
            for instrument_id, step, price in stored.all():
                grid[step - 1][position[instrument_id]] = format(price, "f")
            return grid
        _, request = await load_request(self._session, row.id)
        shard, local = divmod(path, SHARD_SIZE)
        paths = await asyncio.to_thread(generate_shard, request, shard)
        for step in grid:
            for member in members:
                grid[step][member.position] = price_text(float(paths[local, step, member.position]))
        return grid


def _effective_status() -> ColumnElement[str]:
    """The run's status as the API shows it (see ``Reads.runs``)."""
    return case(
        (run.c.status.in_(("queued", "running")) & (job.c.status == "failed"), "failed"),
        else_=run.c.status,
    )
