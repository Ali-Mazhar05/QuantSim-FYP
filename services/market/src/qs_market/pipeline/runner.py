"""Executes an ingestion run (plan sections 5.2 and 5.3).

Each instrument is one database transaction: stage, clean, publish, record quality,
recompute returns and queue the events. A failure rolls the whole instrument back, bars
and events together, so a bar is never published without its event or the reverse.

Run-level rules: an unknown symbol fails only that instrument; a refused key fails the
run and does not count toward the circuit; five consecutive transient vendor failures
open the circuit and defer the rest; an exhausted request budget defers the rest.

Instruments that already succeeded in a previous attempt of the same run (the worker
crashed) are skipped, so a recovered run ends in the same state as an uninterrupted one.
"""

import uuid
from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from qs_market import returns as returns_module
from qs_market.cleaning import RULESET_VERSION, CleanBar, run_gate
from qs_market.models import (
    bar,
    bar_revision,
    corporate_action,
    data_gap,
    ingestion_run,
    ingestion_run_item,
    instrument,
    rejected_bar,
    return_series,
    staging_bar,
)
from qs_market.pipeline.runs import ClaimedRun, claim_next, worker_lock
from qs_market.pipeline.window import resolve_window
from qs_market.vendor.base import (
    BudgetExhausted,
    BudgetUnavailable,
    PriceSource,
    UnknownSymbol,
    VendorAuthError,
    VendorProtocolError,
    VendorTransientError,
)
from qs_template import Database
from qs_template.events import EventEnvelope
from qs_template.logging import get_logger
from qs_template.messaging import add_event

log = get_logger(__name__)

HISTORY_SESSIONS = 61
ADJUSTED_FIELDS = ("adj_open", "adj_high", "adj_low", "adj_close", "adj_volume")
RATIO_STEP = Decimal("0.000000000001")
COUNTERS = (
    "received",
    "passed_untouched",
    "corrected",
    "duplicates_removed",
    "rejected",
    "new_bars",
    "revised",
    "gaps_opened",
    "gaps_resolved",
)


@dataclass(frozen=True)
class PipelineConfig:
    backfill_start: date
    outlier_log_return: float = 0.405
    outlier_policy: Literal["flag", "reject"] = "flag"
    circuit_failures: int = 5


@dataclass(frozen=True)
class RunOutcome:
    run_id: uuid.UUID
    status: str
    error: str | None
    report: dict[str, Any]


def jsonable(value: Any) -> Any:
    """Make a vendor record storable as JSON without ever going through float."""
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [jsonable(v) for v in value]
    if isinstance(value, Decimal | uuid.UUID):
        return str(value)
    if isinstance(value, date):  # datetime too
        return value.isoformat()
    return value


def _ratio(value: float | None) -> Decimal | None:
    return None if value is None else Decimal(repr(value)).quantize(RATIO_STEP)


def _event(
    event_type: str, instrument_id: uuid.UUID, run_id: uuid.UUID, data: dict[str, Any]
) -> EventEnvelope:
    return EventEnvelope(
        event_type=event_type,
        producer="market",
        aggregate_type="instrument",
        aggregate_id=str(instrument_id),
        correlation_id=str(run_id),
        data=data,
    )


async def _recompute_returns(
    session: AsyncSession, instrument_id: uuid.UUID, earliest: date
) -> None:
    history = (
        await session.execute(
            select(bar.c.session_date, bar.c.close, bar.c.adj_close)
            .where(bar.c.instrument_id == instrument_id, bar.c.session_date < earliest)
            .order_by(bar.c.session_date.desc())
            .limit(HISTORY_SESSIONS)
        )
    ).all()
    recent = (
        await session.execute(
            select(bar.c.session_date, bar.c.close, bar.c.adj_close)
            .where(bar.c.instrument_id == instrument_id, bar.c.session_date >= earliest)
            .order_by(bar.c.session_date)
        )
    ).all()
    points = [
        returns_module.PricePoint(r.session_date, r.close, r.adj_close)
        for r in [*reversed(history), *recent]
    ]
    rows = [
        {
            "instrument_id": instrument_id,
            "session_date": p.session_date,
            "log_return": _ratio(p.log_return),
            "adj_log_return": _ratio(p.adj_log_return),
            "vol_20d": _ratio(p.vol_20d),
            "vol_60d": _ratio(p.vol_60d),
        }
        for p in returns_module.compute(points)
        if p.session_date >= earliest
    ]
    if not rows:
        return
    statement = pg_insert(return_series).values(rows)
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=["instrument_id", "session_date"],
            set_={
                "log_return": statement.excluded.log_return,
                "adj_log_return": statement.excluded.adj_log_return,
                "vol_20d": statement.excluded.vol_20d,
                "vol_60d": statement.excluded.vol_60d,
                "computed_at": func.now(),
            },
        )
    )


def _bar_values(
    clean: CleanBar, instrument_id: uuid.UUID, run_id: uuid.UUID, vendor: str
) -> dict[str, Any]:
    return {
        "instrument_id": instrument_id,
        "session_date": clean.session_date,
        "ts": clean.ts,
        "open": clean.open,
        "high": clean.high,
        "low": clean.low,
        "close": clean.close,
        "volume": clean.volume,
        "adj_open": clean.adj_open,
        "adj_high": clean.adj_high,
        "adj_low": clean.adj_low,
        "adj_close": clean.adj_close,
        "adj_volume": clean.adj_volume,
        "split_factor": clean.split_factor,
        "dividend": clean.dividend,
        "content_hash": clean.content_hash,
        "quality_flags": list(clean.flags),
        "run_id": run_id,
        "vendor": vendor,
        "ruleset_version": RULESET_VERSION,
    }


async def _upsert_item(
    session: AsyncSession,
    run_id: uuid.UUID,
    instrument_id: uuid.UUID,
    status: str,
    counters: dict[str, int],
    report: dict[str, Any] | None,
    error: str | None = None,
) -> None:
    values = {
        "run_id": run_id,
        "instrument_id": instrument_id,
        "status": status,
        "error": error,
        "report": report,
        **{name: counters.get(name, 0) for name in COUNTERS},
    }
    statement = pg_insert(ingestion_run_item).values(values)
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=["run_id", "instrument_id"],
            set_={k: v for k, v in values.items() if k not in ("run_id", "instrument_id")},
        )
    )


async def ingest_instrument(
    session: AsyncSession,
    *,
    run: ClaimedRun,
    row: Any,
    source: PriceSource,
    as_of: datetime,
    config: PipelineConfig,
) -> str:
    """One instrument inside the caller's transaction; returns the item status."""
    instrument_id: uuid.UUID = row.id
    window = await resolve_window(
        session,
        calendar=row.calendar,
        instrument_id=instrument_id,
        run_start=run.window_start,
        run_end=run.window_end,
        as_of=as_of,
        backfill_start=config.backfill_start,
    )
    if window is None:
        await _upsert_item(session, run.id, instrument_id, "no_data", {}, {"window": None})
        return "no_data"
    start, end = window

    records = await source.fetch_daily(row.vendor_symbol, start, end)
    if records:
        await session.execute(
            insert(staging_bar),
            [
                {"run_id": run.id, "instrument_id": instrument_id, "payload": jsonable(r)}
                for r in records
            ],
        )

    previous_close = (
        await session.execute(
            select(bar.c.close)
            .where(bar.c.instrument_id == instrument_id, bar.c.session_date < start)
            .order_by(bar.c.session_date.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    gate = run_gate(
        records,
        calendar=row.calendar,
        window_start=start,
        window_end=end,
        as_of=as_of,
        previous_close=previous_close,
        outlier_log_return=config.outlier_log_return,
        outlier_policy=config.outlier_policy,
    )

    # Publish: new sessions inserted, identical hash left alone, changed hash revised
    existing = {
        r.session_date: r
        for r in (
            await session.execute(
                select(bar).where(
                    bar.c.instrument_id == instrument_id, bar.c.session_date.between(start, end)
                )
            )
        ).all()
    }
    new_rows: list[dict[str, Any]] = []
    revised: list[dict[str, Any]] = []
    changed_sessions: list[date] = []
    for clean in gate.clean:
        values = _bar_values(clean, instrument_id, run.id, run.vendor)
        current = existing.get(clean.session_date)
        if current is None:
            new_rows.append(values)
        elif current.content_hash != clean.content_hash:
            previous = {c.name: jsonable(getattr(current, c.name)) for c in bar.columns}
            await session.execute(
                insert(bar_revision).values(
                    instrument_id=instrument_id,
                    session_date=clean.session_date,
                    revision=current.revision,
                    previous=previous,
                    superseded_by_run=run.id,
                )
            )
            await session.execute(
                update(bar)
                .where(
                    bar.c.instrument_id == instrument_id,
                    bar.c.session_date == clean.session_date,
                )
                .values(**values, revision=current.revision + 1, updated_at=func.now())
            )
            revised.append(
                {
                    "session_date": clean.session_date.isoformat(),
                    "revision": current.revision + 1,
                }
            )
            changed_sessions.append(clean.session_date)
        elif any(getattr(current, f) != getattr(clean, f) for f in ADJUSTED_FIELDS):
            # The vendor restated adjusted values; this is not a correction
            await session.execute(
                update(bar)
                .where(
                    bar.c.instrument_id == instrument_id,
                    bar.c.session_date == clean.session_date,
                )
                .values(**{f: getattr(clean, f) for f in ADJUSTED_FIELDS})
            )
    if new_rows:
        await session.execute(insert(bar), new_rows)
        changed_sessions.extend(r["session_date"] for r in new_rows)

    if gate.rejected:
        await session.execute(
            insert(rejected_bar),
            [
                {
                    "run_id": run.id,
                    "instrument_id": instrument_id,
                    "session_date": rej.session_date,
                    "rules": list(rej.rules),
                    "payload": jsonable(rej.payload),
                }
                for rej in gate.rejected
            ],
        )

    # Gaps open once and resolve when the bar arrives
    gaps_opened = 0
    if gate.gaps:
        opened = await session.execute(
            pg_insert(data_gap)
            .values(
                [
                    {"instrument_id": instrument_id, "session_date": g, "opened_by_run": run.id}
                    for g in gate.gaps
                ]
            )
            .on_conflict_do_nothing()
            .returning(data_gap.c.session_date)
        )
        gaps_opened = len(opened.all())
    gaps_resolved = 0
    if gate.clean:
        resolved = await session.execute(
            update(data_gap)
            .where(
                data_gap.c.instrument_id == instrument_id,
                data_gap.c.resolved_at.is_(None),
                data_gap.c.session_date.in_([c.session_date for c in gate.clean]),
            )
            .values(resolved_by_run=run.id, resolved_at=func.now())
            .returning(data_gap.c.session_date)
        )
        gaps_resolved = len(resolved.all())

    actions = [
        {
            "instrument_id": instrument_id,
            "session_date": c.session_date,
            "split_factor": c.split_factor,
            "dividend": c.dividend,
            "vendor": run.vendor,
            "run_id": run.id,
        }
        for c in gate.clean
        if c.split_factor != 1 or c.dividend > 0
    ]
    if actions:
        await session.execute(pg_insert(corporate_action).values(actions).on_conflict_do_nothing())

    if changed_sessions:
        await _recompute_returns(session, instrument_id, min(changed_sessions))

    new_count, revised_count = len(new_rows), len(revised)
    first_session = min(changed_sessions).isoformat() if changed_sessions else None
    last_session = max(changed_sessions).isoformat() if changed_sessions else None
    if new_count or revised_count or gaps_opened:
        await add_event(
            session,
            _event(
                "bar.ingested",
                instrument_id,
                run.id,
                {
                    "instrument_id": str(instrument_id),
                    "symbol": row.symbol,
                    "window_start": start.isoformat(),
                    "window_end": end.isoformat(),
                    "first_session": first_session,
                    "last_session": last_session,
                    "new_bars": new_count,
                    "revised": revised_count,
                    "gaps": [g.isoformat() for g in gate.gaps],
                    "run_id": str(run.id),
                    "vendor": run.vendor,
                    "ruleset_version": RULESET_VERSION,
                },
            ),
        )
    if revised:
        await add_event(
            session,
            _event(
                "bar.corrected",
                instrument_id,
                run.id,
                {
                    "instrument_id": str(instrument_id),
                    "symbol": row.symbol,
                    "sessions": revised,
                    "run_id": str(run.id),
                },
            ),
        )

    report = gate.report
    counters = {
        "received": report["received"],
        "passed_untouched": report["passed_untouched"],
        "corrected": report["corrected"],
        "duplicates_removed": report["duplicates_removed"],
        "rejected": report["rejected"],
        "new_bars": new_count,
        "revised": revised_count,
        "gaps_opened": gaps_opened,
        "gaps_resolved": gaps_resolved,
    }
    status = "succeeded" if records else "no_data"
    await _upsert_item(
        session,
        run.id,
        instrument_id,
        status,
        counters,
        {**report, "window": [start.isoformat(), end.isoformat()]},
    )
    return status


async def _finish(
    database: Database, run: ClaimedRun, status: str, error: str | None
) -> RunOutcome:
    async with database.transaction() as session:
        items = (
            await session.execute(
                select(ingestion_run_item).where(ingestion_run_item.c.run_id == run.id)
            )
        ).all()
        totals: Counter[str] = Counter()
        by_rule: Counter[str] = Counter()
        flagged: Counter[str] = Counter()
        gaps: set[str] = set()
        statuses: Counter[str] = Counter()
        for item in items:
            statuses[item.status] += 1
            for name in COUNTERS:
                totals[name] += getattr(item, name)
            rep = item.report or {}
            by_rule.update(rep.get("by_rule", {}))
            flagged.update(rep.get("flagged", {}))
            gaps.update(f"{item.instrument_id}:{g}" for g in rep.get("gaps", []))
        report: dict[str, Any] = {
            "ruleset_version": RULESET_VERSION,
            **{name: totals[name] for name in COUNTERS},
            "by_rule": dict(sorted(by_rule.items())),
            "flagged": dict(sorted(flagged.items())),
            "gaps": len(gaps),
            "instruments": dict(sorted(statuses.items())),
        }
        await session.execute(
            update(ingestion_run)
            .where(ingestion_run.c.id == run.id)
            .values(
                status=status,
                error=error,
                report=report,
                ruleset_version=RULESET_VERSION,
                finished_at=func.now(),
            )
        )
    log.info("ingestion run finished", run_id=str(run.id), status=status, error=error)
    return RunOutcome(run.id, status, error, report)


async def execute_run(
    database: Database,
    run: ClaimedRun,
    source: PriceSource,
    config: PipelineConfig,
    *,
    as_of: datetime | None = None,
) -> RunOutcome:
    as_of = as_of or datetime.now(UTC)
    async with database.transaction() as session:
        query = select(instrument).where(instrument.c.status == "active")
        if run.instrument_ids is not None:
            query = query.where(instrument.c.id.in_(run.instrument_ids))
        rows = (await session.execute(query.order_by(instrument.c.symbol))).all()
        done = set(
            (
                await session.execute(
                    select(ingestion_run_item.c.instrument_id).where(
                        ingestion_run_item.c.run_id == run.id,
                        ingestion_run_item.c.status.in_(("succeeded", "no_data")),
                    )
                )
            )
            .scalars()
            .all()
        )

    async def record(row: Any, status: str, error: str | None) -> None:
        async with database.transaction() as session:
            await _upsert_item(session, run.id, row.id, status, {}, None, error)

    consecutive = 0
    abort: str | None = None  # a run-level reason that stops the loop
    auth_failed = False
    todo = [r for r in rows if r.id not in done]
    for index, row in enumerate(todo):
        try:
            async with database.transaction() as session:
                await ingest_instrument(
                    session, run=run, row=row, source=source, as_of=as_of, config=config
                )
            consecutive = 0
        except UnknownSymbol as exc:
            await record(row, "failed", f"unknown_symbol: {exc}")
        except VendorAuthError:
            await record(row, "failed", "vendor_auth")
            abort, auth_failed = "vendor_auth", True
        except (VendorTransientError, VendorProtocolError) as exc:
            await record(row, "failed", f"{type(exc).__name__}: {exc}"[:500])
            consecutive += 1
            if consecutive >= config.circuit_failures:
                abort = "circuit_open"
        except BudgetExhausted:
            await record(row, "deferred", "budget_exhausted")
            abort = "budget_exhausted"
        except BudgetUnavailable:
            await record(row, "deferred", "budget_unavailable")
            abort = "budget_unavailable"
        except Exception as exc:
            log.error("instrument failed", symbol=row.symbol, error=str(exc))
            await record(row, "failed", f"{type(exc).__name__}: {exc}"[:500])
        if abort:
            for rest in todo[index + 1 :]:
                await record(rest, "deferred", abort)
            break

    async with database.transaction() as session:
        statuses = set(
            (
                await session.execute(
                    select(ingestion_run_item.c.status).where(ingestion_run_item.c.run_id == run.id)
                )
            )
            .scalars()
            .all()
        )
    good = bool(statuses & {"succeeded", "no_data"})
    if auth_failed:
        status = "failed"
    elif abort in ("circuit_open", "budget_exhausted"):
        status = "partially_succeeded"
    elif statuses <= {"succeeded", "no_data"}:
        status = "succeeded"
    elif good:
        status = "partially_succeeded"
    else:
        status = "failed"
    return await _finish(database, run, status, abort)


async def run_next(
    database: Database,
    make_source: Callable[[ClaimedRun], PriceSource],
    config: PipelineConfig,
    *,
    as_of: datetime | None = None,
    after_claim: Callable[[], Awaitable[None]] | None = None,
) -> RunOutcome | None:
    """Claim and execute one run if this worker holds the lock and one is pending."""
    async with worker_lock(database) as got:
        if not got:
            return None
        async with database.transaction() as session:
            run = await claim_next(session)
        if run is None:
            return None
        if after_claim is not None:
            await after_claim()
        source = make_source(run)
        try:
            return await execute_run(database, run, source, config, as_of=as_of)
        finally:
            closer = getattr(source, "aclose", None)
            if closer is not None:
                await closer()
