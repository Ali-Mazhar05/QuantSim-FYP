"""Ingestion runs (FR-MKT-002, FR-MKT-003, FR-MKT-010, FR-MKT-011, NFR-REL-005).

A run is a row in ``ingestion_run``. The scheduler and the API only *enqueue* runs; a
worker claims and executes them, one at a time across every worker (a PostgreSQL
advisory lock), so two runs never write the same bars concurrently.

For each instrument a run:
1. picks the window: from a few sessions before the last stored bar (to catch late
   vendor corrections) to today, or the run's explicit window;
2. fetches from the vendor and stores the raw records in ``staging_bar``;
3. passes them through the cleaning gate;
4. publishes clean bars idempotently: new sessions are inserted, identical ones are left
   alone, changed ones become a new revision with the old values kept in ``bar_revision``;
5. records rejected bars, data gaps and corporate actions;
6. recomputes returns and volatility from the earliest changed session;
7. publishes ``bar.ingested`` (and ``bar.corrected`` for revisions) through the outbox,
all in one transaction per instrument. Re-running the same window changes nothing.

A worker that dies mid-run leaves its run ``running``; the next worker to take the lock
puts it back to ``pending`` and runs it again, which is safe because every step is
idempotent.
"""

import uuid
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Row, func, insert, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from qs_market import calendars, returns
from qs_market.cleaning import RULESET_VERSION, CleanBar, GateResult, run_gate
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
from qs_market.settings import MarketSettings
from qs_market.sources import PriceSource, RateLimited, SymbolNotFound, VendorError, VendorRejected
from qs_template import Database
from qs_template.events import EventEnvelope
from qs_template.logging import get_logger
from qs_template.messaging import add_event

log = get_logger(__name__)

# Arbitrary, fixed key of the advisory lock that serialises runs
RUN_LOCK_KEY = 7_261_001
RETURNS_HISTORY_SESSIONS = 61  # enough for a full 60-day volatility window


@dataclass
class ItemOutcome:
    status: str
    fetched: int = 0
    passed: int = 0
    corrected: int = 0
    rejected: int = 0
    revised: int = 0
    gaps: int = 0
    error: str | None = None
    report: dict[str, Any] = field(default_factory=dict)


class Ingestion:
    def __init__(
        self,
        settings: MarketSettings,
        database: Database,
        source: PriceSource | None,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._settings = settings
        self._db = database
        self._source = source
        self._clock = clock

    # Queue ----------------------------------------------------------------------------

    async def enqueue(
        self,
        session: AsyncSession,
        *,
        mode: str,
        requested_by: str,
        window_start: date | None = None,
        window_end: date | None = None,
        instrument_ids: Sequence[uuid.UUID] | None = None,
        idempotency_key: str | None = None,
    ) -> uuid.UUID:
        """Add a run to the queue. A repeated ``idempotency_key`` returns the existing run."""
        statement = (
            pg_insert(ingestion_run)
            .values(
                source=self._source.name if self._source else "none",
                mode=mode,
                requested_by=requested_by,
                window_start=window_start,
                window_end=window_end,
                instrument_ids=[str(i) for i in instrument_ids] if instrument_ids else None,
                idempotency_key=idempotency_key,
            )
            .on_conflict_do_nothing(index_elements=["idempotency_key"])
            .returning(ingestion_run.c.id)
        )
        run_id = (await session.execute(statement)).scalar_one_or_none()
        if run_id is None:
            run_id = (
                await session.execute(
                    select(ingestion_run.c.id).where(
                        ingestion_run.c.idempotency_key == idempotency_key
                    )
                )
            ).scalar_one()
        return run_id

    async def schedule_due(self, now: datetime) -> list[uuid.UUID]:
        """Enqueue today's daily and catch-up runs once their time has passed. Safe to
        call often and from several processes: each run has a per-day idempotency key."""
        due = [
            (mode, at)
            for mode, at in (
                ("daily", self._settings.daily_run_at),
                ("catchup", self._settings.catchup_run_at),
            )
            if now.time() >= at
        ]
        created = []
        async with self._db.transaction() as session:
            for mode, _ in due:
                created.append(
                    await self.enqueue(
                        session,
                        mode=mode,
                        requested_by="scheduler",
                        idempotency_key=f"{mode}-{now.date().isoformat()}",
                    )
                )
        return created

    # Worker ---------------------------------------------------------------------------

    async def work_once(self) -> uuid.UUID | None:
        """Take the run lock, then claim and execute the oldest pending run. Returns the
        run executed, or None when there was nothing to do or another worker is busy."""
        async with self._db.engine.connect() as lock_connection:
            locked = await lock_connection.scalar(
                text("SELECT pg_try_advisory_lock(:key)"), {"key": RUN_LOCK_KEY}
            )
            await lock_connection.commit()
            if not locked:
                return None
            try:
                await self._recover_stale_runs()
                run_id = await self._claim_next()
                if run_id is not None:
                    await self.execute(run_id)
                return run_id
            finally:
                await lock_connection.execute(
                    text("SELECT pg_advisory_unlock(:key)"), {"key": RUN_LOCK_KEY}
                )
                await lock_connection.commit()

    async def _recover_stale_runs(self) -> None:
        # We hold the lock, so any run still marked running belongs to a dead worker
        async with self._db.transaction() as session:
            recovered = await session.execute(
                update(ingestion_run)
                .where(ingestion_run.c.status == "running")
                .values(status="pending", started_at=None)
                .returning(ingestion_run.c.id)
            )
            for run_id in recovered.scalars():
                log.warning("recovered a run left running by a stopped worker", run_id=str(run_id))
                await session.execute(
                    ingestion_run_item.delete().where(ingestion_run_item.c.run_id == run_id)
                )

    async def _claim_next(self) -> uuid.UUID | None:
        async with self._db.transaction() as session:
            oldest = (
                select(ingestion_run.c.id)
                .where(ingestion_run.c.status == "pending")
                .order_by(ingestion_run.c.created_at)
                .limit(1)
                .with_for_update(skip_locked=True)
                .scalar_subquery()
            )
            claimed = await session.execute(
                update(ingestion_run)
                .where(ingestion_run.c.id == oldest)
                .values(status="running", started_at=func.now())
                .returning(ingestion_run.c.id)
            )
            run_id: uuid.UUID | None = claimed.scalar_one_or_none()
            return run_id

    # Execution ------------------------------------------------------------------------

    async def execute(self, run_id: uuid.UUID) -> str:
        async with self._db.transaction() as session:
            run = (
                await session.execute(select(ingestion_run).where(ingestion_run.c.id == run_id))
            ).one()
            query = select(instrument).order_by(instrument.c.symbol)
            if run.instrument_ids:
                query = query.where(instrument.c.id.in_([uuid.UUID(i) for i in run.instrument_ids]))
            else:
                query = query.where(instrument.c.status == "active")
            instruments = (await session.execute(query)).all()

        if self._source is None:
            return await self._finish(run_id, "failed", {}, error="no price vendor is configured")

        log.info("ingestion run started", run_id=str(run_id), instruments=len(instruments))
        outcomes: dict[str, ItemOutcome] = {}
        consecutive_failures = 0
        stop_reason: str | None = None

        for inst in instruments:
            if stop_reason:
                outcome = ItemOutcome(status="deferred", error=stop_reason)
            else:
                try:
                    outcome = await self._ingest_instrument(run, inst)
                    consecutive_failures = 0
                except RateLimited as exc:
                    stop_reason = f"request budget used up: {exc}"
                    outcome = ItemOutcome(status="deferred", error=stop_reason)
                except (SymbolNotFound, VendorRejected) as exc:
                    outcome = ItemOutcome(status="failed", error=str(exc))
                except VendorError as exc:
                    consecutive_failures += 1
                    outcome = ItemOutcome(status="failed", error=str(exc))
                    if consecutive_failures >= self._settings.circuit_breaker_threshold:
                        stop_reason = (
                            f"vendor failed {consecutive_failures} times in a row; "
                            "remaining instruments deferred"
                        )
                        log.error("circuit breaker opened", run_id=str(run_id))
                except Exception as exc:
                    log.exception("instrument ingestion failed", symbol=inst.symbol)
                    consecutive_failures += 1
                    outcome = ItemOutcome(status="failed", error=f"internal error: {exc}")
            outcomes[inst.symbol] = outcome
            await self._record_item(run_id, inst.id, outcome)

        statuses = Counter(o.status for o in outcomes.values())
        ok = statuses["succeeded"] + statuses["no_data"]
        if not outcomes or ok == len(outcomes):
            status = "succeeded"
        elif ok:
            status = "partially_succeeded"
        else:
            status = "failed"
        return await self._finish(run_id, status, outcomes, error=stop_reason)

    async def _finish(
        self,
        run_id: uuid.UUID,
        status: str,
        outcomes: dict[str, ItemOutcome],
        *,
        error: str | None = None,
    ) -> str:
        totals: Counter[str] = Counter()
        by_rule: Counter[str] = Counter()
        flagged: Counter[str] = Counter()
        for outcome in outcomes.values():
            totals.update(
                {
                    k: getattr(outcome, k)
                    for k in ("fetched", "passed", "corrected", "rejected", "revised", "gaps")
                }
            )
            by_rule.update(outcome.report.get("by_rule", {}))
            flagged.update(outcome.report.get("flagged", {}))
        report = {
            "ruleset_version": RULESET_VERSION,
            "instruments": len(outcomes),
            "statuses": dict(Counter(o.status for o in outcomes.values())),
            "totals": dict(totals),
            "by_rule": dict(sorted(by_rule.items())),
            "flagged": dict(sorted(flagged.items())),
            "per_instrument": {
                symbol: {k: v for k, v in asdict(o).items() if k != "report"} | {
                    "gaps_list": o.report.get("gaps", [])
                }
                for symbol, o in outcomes.items()
            },
        }
        async with self._db.transaction() as session:
            await session.execute(
                update(ingestion_run)
                .where(ingestion_run.c.id == run_id)
                .values(
                    status=status,
                    report=report,
                    error=error,
                    ruleset_version=RULESET_VERSION,
                    finished_at=func.now(),
                )
            )
        log.info("ingestion run finished", run_id=str(run_id), status=status, **dict(totals))
        return status

    async def _record_item(
        self, run_id: uuid.UUID, instrument_id: uuid.UUID, outcome: ItemOutcome
    ) -> None:
        async with self._db.transaction() as session:
            await session.execute(
                pg_insert(ingestion_run_item)
                .values(
                    run_id=run_id,
                    instrument_id=instrument_id,
                    status=outcome.status,
                    fetched=outcome.fetched,
                    passed=outcome.passed,
                    corrected=outcome.corrected,
                    rejected=outcome.rejected,
                    revised=outcome.revised,
                    gaps=outcome.gaps,
                    error=outcome.error,
                )
                .on_conflict_do_nothing()
            )

    async def _window(self, session: AsyncSession, run: Row[Any], inst: Row[Any]) -> tuple[date, date]:
        end = run.window_end or self._clock().date()
        if run.window_start:
            return run.window_start, end
        last = (
            await session.execute(
                select(func.max(bar.c.session_date)).where(bar.c.instrument_id == inst.id)
            )
        ).scalar_one_or_none()
        if last is None:
            return date.fromisoformat(self._settings.backfill_start), end
        return calendars.sessions_before(inst.calendar, last, self._settings.lookback_sessions), end

    async def _ingest_instrument(self, run: Row[Any], inst: Row[Any]) -> ItemOutcome:
        assert self._source is not None
        async with self._db.transaction() as session:
            start, end = await self._window(session, run, inst)
        if start > end:
            return ItemOutcome(status="no_data")

        raw = await self._source.fetch_daily(inst.vendor_symbol, start, end)
        records = [self._source.normalise(r) for r in raw]
        as_of = self._clock()

        async with self._db.transaction() as session:
            if raw:
                await session.execute(
                    insert(staging_bar),
                    [{"run_id": run.id, "instrument_id": inst.id, "payload": r} for r in raw],
                )
            previous_close = (
                await session.execute(
                    select(bar.c.close)
                    .where(bar.c.instrument_id == inst.id, bar.c.session_date < start)
                    .order_by(bar.c.session_date.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            result = run_gate(
                records,
                calendar=inst.calendar,
                window_start=start,
                window_end=end,
                as_of=as_of,
                previous_close=previous_close,
                outlier_log_return=self._settings.outlier_log_return,
                outlier_policy=self._settings.outlier_policy,
            )
            inserted, revised = await self._publish(session, run.id, inst.id, result.clean)
            await self._record_quality(session, run.id, inst.id, result)
            changed = sorted(inserted | revised)
            if changed:
                await self._recompute_returns(session, inst, changed[0])
                await self._publish_events(session, run.id, inst, result, inserted, revised)

        report = result.report
        return ItemOutcome(
            status="succeeded" if raw else "no_data",
            fetched=len(raw),
            passed=report["passed_untouched"],
            corrected=report["corrected"],
            rejected=report["rejected"],
            revised=len(revised),
            gaps=len(result.gaps),
            report=report,
        )

    async def _publish(
        self,
        session: AsyncSession,
        run_id: uuid.UUID,
        instrument_id: uuid.UUID,
        clean: list[CleanBar],
    ) -> tuple[set[date], set[date]]:
        if not clean:
            return set(), set()
        existing = {
            row.session_date: row
            for row in (
                await session.execute(
                    select(bar).where(
                        bar.c.instrument_id == instrument_id,
                        bar.c.session_date.in_([b.session_date for b in clean]),
                    )
                )
            ).all()
        }
        inserted: set[date] = set()
        revised: set[date] = set()
        new_rows = []
        source = self._source.name if self._source else "none"
        for b in clean:
            values = _bar_values(b, source)
            current = existing.get(b.session_date)
            if current is None:
                new_rows.append(
                    {"instrument_id": instrument_id, "run_id": run_id, "revision": 1, **values}
                )
                inserted.add(b.session_date)
            elif current.content_hash != b.content_hash:
                await session.execute(
                    insert(bar_revision).values(
                        instrument_id=instrument_id,
                        session_date=b.session_date,
                        revision=current.revision,
                        previous=_row_json(current),
                        run_id=run_id,
                    )
                )
                await session.execute(
                    update(bar)
                    .where(bar.c.instrument_id == instrument_id, bar.c.session_date == b.session_date)
                    .values(
                        **values,
                        revision=current.revision + 1,
                        run_id=run_id,
                        updated_at=func.now(),
                    )
                )
                revised.add(b.session_date)
        if new_rows:
            await session.execute(insert(bar), new_rows)
        return inserted, revised

    async def _record_quality(
        self, session: AsyncSession, run_id: uuid.UUID, instrument_id: uuid.UUID, result: GateResult
    ) -> None:
        if result.rejected:
            await session.execute(
                insert(rejected_bar),
                [
                    {
                        "run_id": run_id,
                        "instrument_id": instrument_id,
                        "session_date": r.session_date,
                        "rules": list(r.rules),
                        "payload": _jsonable(r.payload),
                    }
                    for r in result.rejected
                ],
            )
        if result.gaps:
            await session.execute(
                pg_insert(data_gap)
                .values(
                    [
                        {"instrument_id": instrument_id, "session_date": g, "first_seen_run": run_id}
                        for g in result.gaps
                    ]
                )
                .on_conflict_do_nothing()
            )
        if result.clean:
            await session.execute(
                update(data_gap)
                .where(
                    data_gap.c.instrument_id == instrument_id,
                    data_gap.c.resolved_at.is_(None),
                    data_gap.c.session_date.in_([b.session_date for b in result.clean]),
                )
                .values(resolved_at=func.now())
            )
        actions = [b for b in result.clean if b.split_factor != 1 or b.dividend != 0]
        if actions:
            statement = pg_insert(corporate_action).values(
                [
                    {
                        "instrument_id": instrument_id,
                        "session_date": b.session_date,
                        "split_factor": b.split_factor,
                        "dividend": b.dividend,
                        "source": self._source.name if self._source else "none",
                    }
                    for b in actions
                ]
            )
            await session.execute(
                statement.on_conflict_do_update(
                    index_elements=["instrument_id", "session_date"],
                    set_={
                        "split_factor": statement.excluded.split_factor,
                        "dividend": statement.excluded.dividend,
                    },
                )
            )

    async def _recompute_returns(self, session: AsyncSession, inst: Row[Any], since: date) -> None:
        history_start = calendars.sessions_before(inst.calendar, since, RETURNS_HISTORY_SESSIONS)
        rows = (
            await session.execute(
                select(bar.c.session_date, bar.c.close, bar.c.adj_close)
                .where(bar.c.instrument_id == inst.id, bar.c.session_date >= history_start)
                .order_by(bar.c.session_date)
            )
        ).all()
        points = [returns.PricePoint(r.session_date, r.close, r.adj_close) for r in rows]
        values = [
            {
                "instrument_id": inst.id,
                "session_date": p.session_date,
                "log_return": p.log_return,
                "adj_log_return": p.adj_log_return,
                "vol_20d": p.vol_20d,
                "vol_60d": p.vol_60d,
            }
            for p in returns.compute(points)
            if p.session_date >= since
        ]
        if not values:
            return
        statement = pg_insert(return_series).values(values)
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

    async def _publish_events(
        self,
        session: AsyncSession,
        run_id: uuid.UUID,
        inst: Row[Any],
        result: GateResult,
        inserted: set[date],
        revised: set[date],
    ) -> None:
        changed = sorted(inserted | revised)
        common = {"instrument_id": str(inst.id), "symbol": inst.symbol, "run_id": str(run_id)}
        await add_event(
            session,
            EventEnvelope(
                event_type="bar.ingested",
                producer="market",
                aggregate_type="instrument",
                aggregate_id=str(inst.id),
                data={
                    **common,
                    "from": changed[0].isoformat(),
                    "to": changed[-1].isoformat(),
                    "new_bars": len(inserted),
                    "revised_bars": len(revised),
                    "gaps": [g.isoformat() for g in result.gaps],
                },
            ),
        )
        if revised:
            await add_event(
                session,
                EventEnvelope(
                    event_type="bar.corrected",
                    producer="market",
                    aggregate_type="instrument",
                    aggregate_id=str(inst.id),
                    data={**common, "sessions": [d.isoformat() for d in sorted(revised)]},
                ),
            )


def _bar_values(b: CleanBar, source: str) -> dict[str, Any]:
    return {
        "session_date": b.session_date,
        "ts": b.ts,
        "open": b.open,
        "high": b.high,
        "low": b.low,
        "close": b.close,
        "volume": b.volume,
        "adj_close": b.adj_close,
        "split_factor": b.split_factor,
        "dividend": b.dividend,
        "source": source,
        "content_hash": b.content_hash,
        "quality_flags": list(b.flags),
    }


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    if isinstance(value, (Decimal, date, datetime, uuid.UUID)):
        return str(value)
    return value


def _row_json(row: Row[Any]) -> dict[str, Any]:
    return {k: _jsonable(v) for k, v in row._mapping.items()}
