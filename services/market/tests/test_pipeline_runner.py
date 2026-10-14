"""The ingestion pipeline against a real PostgreSQL with TimescaleDB, with recorded vendor
responses and hand-written fake vendors (never the real one)."""

import asyncio
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr
from sqlalchemy import func, insert, select, text

from qs_market import returns as returns_module
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
from qs_market.pipeline import runner
from qs_market.pipeline.runner import PipelineConfig, RunOutcome, run_next
from qs_market.pipeline.runs import RunConflict, claim_next, create_run, worker_lock
from qs_market.settings import MarketSettings
from qs_market.vendor.base import (
    BudgetExhausted,
    UnknownSymbol,
    VendorAuthError,
    VendorTransientError,
)
from qs_market.vendor.fixture import FixtureSource
from qs_template import Database
from qs_template.messaging import outbox

pytestmark = pytest.mark.db

FIXTURES = Path(__file__).parent / "fixtures"
AS_OF = datetime(2025, 1, 6, 12, 0, tzinfo=UTC)
AAPL_WINDOW = (date(2024, 1, 2), date(2024, 2, 13))
NVDA_WINDOW = (date(2024, 5, 28), date(2024, 6, 21))
CONFIG = PipelineConfig(backfill_start=date(2024, 1, 2))
TABLES = (
    "outbox, return_series, corporate_action, data_gap, rejected_bar, staging_bar, bar_revision, "
    "bar, ingestion_run_item, ingestion_run, instrument"
)


class Killed(BaseException):
    """Stands in for a worker process dying (not an Exception, so nothing catches it)."""


class Scripted:
    """A vendor over the recorded fixtures with per-symbol behaviour injected."""

    name = "fixture"

    def __init__(
        self,
        failures: dict[str, BaseException] | None = None,
        edit: Any = None,
    ) -> None:
        self._inner = FixtureSource(FIXTURES)
        self.failures = failures or {}
        self.edit = edit
        self.calls: list[str] = []

    async def fetch_daily(self, symbol: str, start: date, end: date) -> list[dict[str, Any]]:
        self.calls.append(symbol)
        if symbol in self.failures:
            raise self.failures[symbol]
        rows = await self._inner.fetch_daily(symbol, start, end)
        return self.edit(symbol, rows) if self.edit else rows


@pytest.fixture
async def db(migrated_database_url: str) -> AsyncIterator[Database]:
    settings = MarketSettings(
        database_url=SecretStr(migrated_database_url), redis_url=SecretStr("redis://unused")
    )
    database = Database(settings)
    async with database.transaction() as session:
        await session.execute(text(f"TRUNCATE {TABLES} CASCADE"))
    yield database
    # The database is shared by the whole session; leave it as it was found
    async with database.transaction() as session:
        await session.execute(text(f"TRUNCATE {TABLES} CASCADE"))
    await database.close()


async def add_instrument(db: Database, symbol: str, vendor_symbol: str | None = None) -> uuid.UUID:
    async with db.transaction() as session:
        return (
            await session.execute(
                insert(instrument)
                .values(
                    symbol=symbol,
                    name=symbol,
                    sector="Technology",
                    exchange="XNAS",
                    calendar="XNYS",
                    currency="USD",
                    asset_class="equity",
                    vendor_symbol=vendor_symbol or symbol,
                )
                .returning(instrument.c.id)
            )
        ).scalar_one()


async def go(
    db: Database,
    source: Any,
    *,
    window: tuple[date | None, date | None] | None = None,
    ids: list[uuid.UUID] | None = None,
    mode: str = "manual",
    config: PipelineConfig = CONFIG,
) -> RunOutcome:
    async with db.transaction() as session:
        await create_run(
            session,
            mode=mode,
            window=window,
            instrument_ids=ids,
            idempotency_key=None,
            requested_by="tests",
            vendor="fixture",
        )
    outcome = await run_next(db, lambda run: source, config, as_of=AS_OF)
    assert outcome is not None
    return outcome


async def count(db: Database, table: Any) -> int:
    async with db.transaction() as session:
        return int((await session.execute(select(func.count()).select_from(table))).scalar_one())


async def events(db: Database, kind: str | None = None) -> list[dict[str, Any]]:
    async with db.transaction() as session:
        query = select(outbox.c.event_type, outbox.c.payload).order_by(outbox.c.id)
        if kind:
            query = query.where(outbox.c.event_type == kind)
        return [dict(r.payload) for r in (await session.execute(query)).all()]


async def snapshot(db: Database) -> dict[str, Any]:
    async with db.transaction() as session:
        bars = (
            await session.execute(
                select(
                    instrument.c.symbol,
                    bar.c.session_date,
                    bar.c.close,
                    bar.c.revision,
                    bar.c.content_hash,
                )
                .select_from(bar.join(instrument, instrument.c.id == bar.c.instrument_id))
                .order_by(instrument.c.symbol, bar.c.session_date)
            )
        ).all()
        revisions = (
            await session.execute(
                select(bar_revision.c.session_date, bar_revision.c.revision).order_by(
                    bar_revision.c.session_date
                )
            )
        ).all()
        rets = (
            await session.execute(
                select(return_series.c.session_date, return_series.c.log_return).order_by(
                    return_series.c.session_date, return_series.c.log_return
                )
            )
        ).all()
    evs = [
        (e["event_type"], {**e["data"], "run_id": None, "instrument_id": None})
        for e in await events(db)
    ]
    return {
        "bars": [tuple(r) for r in bars],
        "revisions": [tuple(r) for r in revisions],
        "returns": [tuple(r) for r in rets],
        "events": sorted(evs, key=lambda e: (e[0], str(e[1]))),
    }


def restate_adjusted(symbol: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{**r, "adj_close": r["adj_close"] * Decimal("0.99")} for r in rows]


def change_close(symbol: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = [dict(r) for r in rows]
    out[3]["close"] = out[3]["close"] - Decimal("0.01")
    return out


async def test_first_run_inserts_and_identical_second_run_adds_nothing(db: Database) -> None:
    aapl = await add_instrument(db, "AAPL")
    first = await go(db, Scripted(), window=AAPL_WINDOW, ids=[aapl])
    assert first.status == "succeeded"
    assert first.report["new_bars"] == 30
    assert first.report["received"] == first.report["passed_untouched"] == 30
    bars, outbox_rows = await count(db, bar), await count(db, outbox)
    assert bars == 30
    assert len(await events(db, "bar.ingested")) == 1

    second = await go(db, Scripted(), window=AAPL_WINDOW, ids=[aapl])
    assert second.status == "succeeded"
    assert second.report["new_bars"] == 0 and second.report["revised"] == 0
    assert await count(db, bar) == bars
    assert await count(db, outbox) == outbox_rows
    assert await count(db, bar_revision) == 0

    async with db.transaction() as session:
        stored = (await session.execute(select(bar).limit(1))).one()
    assert stored.vendor == "fixture"
    assert stored.ruleset_version
    assert stored.revision == 1
    assert isinstance(stored.close, Decimal)


async def test_changed_raw_value_is_a_revision_with_one_corrected_event(db: Database) -> None:
    aapl = await add_instrument(db, "AAPL")
    await go(db, Scripted(), window=AAPL_WINDOW, ids=[aapl])
    outcome = await go(db, Scripted(edit=change_close), window=AAPL_WINDOW, ids=[aapl])
    assert outcome.report["revised"] == 1 and outcome.report["new_bars"] == 0
    assert await count(db, bar_revision) == 1
    corrected = await events(db, "bar.corrected")
    assert len(corrected) == 1
    assert len(corrected[0]["data"]["sessions"]) == 1
    async with db.transaction() as session:
        revised = (await session.execute(select(bar).where(bar.c.revision == 2))).all()
        old = (await session.execute(select(bar_revision.c.previous))).scalar_one()
    assert len(revised) == 1
    assert Decimal(old["close"]) == revised[0].close + Decimal("0.01")
    assert revised[0].run_id == outcome.run_id


async def test_restated_adjusted_price_alone_is_not_a_revision(db: Database) -> None:
    aapl = await add_instrument(db, "AAPL")
    await go(db, Scripted(), window=AAPL_WINDOW, ids=[aapl])
    events_before = await count(db, outbox)
    outcome = await go(db, Scripted(edit=restate_adjusted), window=AAPL_WINDOW, ids=[aapl])
    assert outcome.report["revised"] == 0
    assert await count(db, bar_revision) == 0
    assert await count(db, outbox) == events_before
    async with db.transaction() as session:
        adj = (await session.execute(select(bar.c.adj_close, bar.c.close).limit(1))).one()
    assert adj.adj_close is not None
    assert (await snapshot(db))["bars"][0][3] == 1


async def test_rejected_bars_keep_every_rule_and_gap_opens_then_resolves(db: Database) -> None:
    aapl = await add_instrument(db, "AAPL")

    def damage(symbol: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out = [dict(r) for r in rows]
        out[5]["low"] = out[5]["high"] + 1  # ohlc_order, and open/close outside the range
        out[6]["volume"] = Decimal(-1)  # negative_volume
        out[7]["open"] = Decimal(0)  # non_positive_price (and ohlc order)
        return out

    first = await go(db, Scripted(edit=damage), window=AAPL_WINDOW, ids=[aapl])
    assert first.report["rejected"] == 3
    assert first.report["gaps"] == 3
    async with db.transaction() as session:
        rejected = (await session.execute(select(rejected_bar.c.rules))).scalars().all()
        open_gaps = (
            await session.execute(select(data_gap).where(data_gap.c.resolved_at.is_(None)))
        ).all()
    assert sorted(r[0] for r in rejected) == ["negative_volume", "non_positive_price", "ohlc_order"]
    assert len(open_gaps) == 3
    item = await first_item(db)
    assert item.gaps_opened == 3 and item.rejected == 3

    again = await go(db, Scripted(), window=AAPL_WINDOW, ids=[aapl])
    assert again.report["gaps_resolved"] == 3
    async with db.transaction() as session:
        still_open = (
            await session.execute(
                select(func.count()).select_from(data_gap).where(data_gap.c.resolved_at.is_(None))
            )
        ).scalar_one()
    assert still_open == 0
    assert await count(db, bar) == 30


async def first_item(db: Database) -> Any:
    async with db.transaction() as session:
        return (
            await session.execute(
                select(ingestion_run_item)
                .join(ingestion_run, ingestion_run.c.id == ingestion_run_item.c.run_id)
                .order_by(ingestion_run.c.created_at, ingestion_run.c.id)
                .limit(1)
            )
        ).one()


async def test_corporate_actions_are_stored_once_and_returns_match_compute(db: Database) -> None:
    aapl = await add_instrument(db, "AAPL")
    nvda = await add_instrument(db, "NVDA")
    await go(db, Scripted(), window=AAPL_WINDOW, ids=[aapl])
    await go(db, Scripted(), window=NVDA_WINDOW, ids=[nvda])
    await go(db, Scripted(), window=AAPL_WINDOW, ids=[aapl])
    async with db.transaction() as session:
        actions = (
            await session.execute(
                select(
                    corporate_action.c.session_date,
                    corporate_action.c.split_factor,
                    corporate_action.c.dividend,
                ).order_by(corporate_action.c.session_date)
            )
        ).all()
    assert [(a.session_date, a.split_factor, a.dividend) for a in actions] == [
        (date(2024, 2, 9), Decimal(1), Decimal("0.24")),
        (date(2024, 6, 10), Decimal(10), Decimal(0)),
        (date(2024, 6, 11), Decimal(1), Decimal("0.01")),
    ]
    async with db.transaction() as session:
        bars = (
            await session.execute(
                select(bar.c.session_date, bar.c.close, bar.c.adj_close)
                .where(bar.c.instrument_id == aapl)
                .order_by(bar.c.session_date)
            )
        ).all()
        stored = (
            await session.execute(
                select(return_series)
                .where(return_series.c.instrument_id == aapl)
                .order_by(return_series.c.session_date)
            )
        ).all()
    expected = returns_module.compute(
        [returns_module.PricePoint(b.session_date, b.close, b.adj_close) for b in bars]
    )
    assert len(stored) == len(expected) == 30
    step = Decimal("0.000000000001")

    def exact(value: float | None) -> Decimal | None:
        return None if value is None else Decimal(repr(value)).quantize(step)

    for got, want in zip(stored, expected, strict=True):
        assert got.log_return == exact(want.log_return)
        assert got.adj_log_return == exact(want.adj_log_return)
        assert got.vol_20d == exact(want.vol_20d)
    assert stored[-1].vol_20d is not None


async def test_one_bad_symbol_fails_only_that_item(db: Database) -> None:
    aapl = await add_instrument(db, "AAPL")
    bad = await add_instrument(db, "ZZZZ")
    outcome = await go(db, Scripted(), window=AAPL_WINDOW, ids=[aapl, bad])
    assert outcome.status == "partially_succeeded"
    assert await count(db, bar) == 30
    async with db.transaction() as session:
        statuses = dict(
            (
                await session.execute(
                    select(ingestion_run_item.c.instrument_id, ingestion_run_item.c.status)
                )
            ).all()
        )
    assert statuses == {aapl: "succeeded", bad: "failed"}


async def test_vendor_refusing_the_key_fails_the_run(db: Database) -> None:
    ids = [await add_instrument(db, s) for s in ("AAPL", "NVDA")]
    outcome = await go(
        db, Scripted(failures={"AAPL": VendorAuthError("401")}), window=AAPL_WINDOW, ids=ids
    )
    assert outcome.status == "failed"
    assert outcome.error == "vendor_auth"
    assert await count(db, bar) == 0
    async with db.transaction() as session:
        statuses = (
            (await session.execute(select(ingestion_run_item.c.status).order_by("status")))
            .scalars()
            .all()
        )
    assert statuses == ["deferred", "failed"]


async def test_five_transient_failures_open_the_circuit(db: Database) -> None:
    ids = [await add_instrument(db, f"T{i}") for i in range(8)]
    failures: dict[str, BaseException] = {f"T{i}": VendorTransientError("down") for i in range(8)}
    source = Scripted(failures=failures)
    outcome = await go(db, source, window=AAPL_WINDOW, ids=ids)
    assert outcome.status == "partially_succeeded"
    assert outcome.error == "circuit_open"
    assert len(source.calls) == 5
    assert outcome.report["instruments"] == {"deferred": 3, "failed": 5}


async def test_unknown_symbols_do_not_count_toward_the_circuit(db: Database) -> None:
    ids = [await add_instrument(db, f"U{i}") for i in range(7)]
    source = Scripted(failures={f"U{i}": UnknownSymbol("no") for i in range(7)})
    outcome = await go(db, source, window=AAPL_WINDOW, ids=ids)
    assert outcome.status == "failed"
    assert len(source.calls) == 7


async def test_budget_exhausted_defers_the_rest(db: Database) -> None:
    aapl = await add_instrument(db, "AAPL")
    nvda = await add_instrument(db, "NVDA")
    outcome = await go(
        db,
        Scripted(failures={"NVDA": BudgetExhausted("spent")}),
        window=(date(2024, 1, 2), date(2024, 2, 13)),
        ids=[aapl, nvda],
    )
    assert outcome.status == "partially_succeeded"
    assert outcome.error == "budget_exhausted"
    assert outcome.report["instruments"] == {"deferred": 1, "succeeded": 1}


async def test_window_without_a_session_succeeds_with_nothing(db: Database) -> None:
    aapl = await add_instrument(db, "AAPL")
    source = Scripted()
    saturday = date(2024, 1, 6)
    outcome = await go(db, source, window=(saturday, date(2024, 1, 7)), ids=[aapl])
    assert outcome.status == "succeeded"
    assert source.calls == []
    assert await count(db, outbox) == 0 and await count(db, bar) == 0


async def test_default_window_overlaps_five_sessions(db: Database) -> None:
    aapl = await add_instrument(db, "AAPL")
    await go(db, Scripted(), window=AAPL_WINDOW, ids=[aapl])
    seen: list[tuple[date, date]] = []

    class Spy(Scripted):
        async def fetch_daily(self, symbol: str, start: date, end: date) -> list[dict[str, Any]]:
            seen.append((start, end))
            return await super().fetch_daily(symbol, start, end)

    outcome = await go(db, Spy(), ids=[aapl], mode="catchup")
    assert seen[0][0] == date(2024, 2, 6)  # five sessions before 2024-02-13
    assert seen[0][1] == date(2025, 1, 3)  # latest closed session at AS_OF
    assert outcome.report["new_bars"] == 0


async def test_two_workers_only_one_executes(db: Database) -> None:
    aapl = await add_instrument(db, "AAPL")
    async with db.transaction() as session:
        await create_run(
            session,
            mode="manual",
            window=AAPL_WINDOW,
            instrument_ids=[aapl],
            idempotency_key=None,
            requested_by="t",
            vendor="fixture",
        )
    entered, release = asyncio.Event(), asyncio.Event()

    async def hold() -> None:
        entered.set()
        await release.wait()

    first = asyncio.create_task(
        run_next(db, lambda run: Scripted(), CONFIG, as_of=AS_OF, after_claim=hold)
    )
    await entered.wait()
    assert await run_next(db, lambda run: Scripted(), CONFIG, as_of=AS_OF) is None
    async with worker_lock(db) as got:
        assert got is False
    release.set()
    outcome = await first
    assert outcome is not None and outcome.status == "succeeded"
    async with worker_lock(db) as got:
        assert got is True


async def test_crashed_run_is_recovered_to_the_same_state(db: Database) -> None:
    ids = [await add_instrument(db, s) for s in ("AAPL", "NVDA")]

    async def run_with(source: Scripted) -> RunOutcome:
        return await go(db, source, window=(date(2024, 1, 2), date(2024, 6, 21)), ids=ids)

    # An uninterrupted run is the reference
    reference = await run_with(Scripted())
    expected = await snapshot(db)
    async with db.transaction() as session:
        await session.execute(text(f"TRUNCATE {TABLES} CASCADE"))
    ids = [await add_instrument(db, s) for s in ("AAPL", "NVDA")]

    # The worker dies while fetching the second instrument; the first one is committed
    with pytest.raises(Killed):
        await run_with(Scripted(failures={"NVDA": Killed()}))
    async with db.transaction() as session:
        status = (await session.execute(select(ingestion_run.c.status))).scalar_one()
    assert status == "running"
    assert await count(db, bar) > 0

    # The next worker claims it again and finishes without redoing the first instrument
    source = Scripted()
    outcome = await run_next(db, lambda run: source, CONFIG, as_of=AS_OF)
    assert outcome is not None
    assert source.calls == ["NVDA"]
    assert outcome.status == reference.status
    assert outcome.report["new_bars"] == reference.report["new_bars"]
    assert await snapshot(db) == expected


async def test_event_and_bars_commit_together(
    db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    aapl = await add_instrument(db, "AAPL")
    real = runner.add_event

    async def add_then_fail(session: Any, event: Any) -> None:
        await real(session, event)
        raise RuntimeError("fails after the event was queued")

    monkeypatch.setattr(runner, "add_event", add_then_fail)
    outcome = await go(db, Scripted(), window=AAPL_WINDOW, ids=[aapl])
    assert outcome.status == "failed"
    for table in (bar, outbox, staging_bar, return_series, corporate_action, rejected_bar):
        assert await count(db, table) == 0


async def test_run_report_adds_up_for_every_outcome(db: Database) -> None:
    aapl = await add_instrument(db, "AAPL")
    nvda = await add_instrument(db, "NVDA")

    def duplicate_and_damage(symbol: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [*rows, dict(rows[0]), {**rows[1], "close": rows[1]["close"] + 1}]

    outcome = await go(db, Scripted(edit=duplicate_and_damage), window=AAPL_WINDOW, ids=[aapl])
    report = outcome.report
    assert report["duplicates_removed"] == 1
    assert report["corrected"] == 1
    assert report["rejected"] == 2  # both copies of the conflicting session
    assert report["received"] == (
        report["passed_untouched"]
        + report["corrected"]
        + report["duplicates_removed"]
        + report["rejected"]
    )
    assert report["by_rule"] == {"duplicate_conflict": 2, "duplicate_removed": 1}
    # a failed and a deferred item also satisfy the database CHECK
    await go(db, Scripted(failures={"NVDA": UnknownSymbol("x")}), window=NVDA_WINDOW, ids=[nvda])
    async with db.transaction() as session:
        run_report = (await session.execute(select(ingestion_run.c.report))).scalars().first()
    assert run_report is not None


async def test_idempotency_key_and_conflict(db: Database) -> None:
    aapl = await add_instrument(db, "AAPL")

    async def create(key: str | None, ids: list[uuid.UUID] | None) -> Any:
        async with db.transaction() as session:
            return await create_run(
                session,
                mode="daily",
                window=None,
                instrument_ids=ids,
                idempotency_key=key,
                requested_by="scheduler",
                vendor="fixture",
            )

    first = await create("daily:2025-01-06", None)
    second = await create("daily:2025-01-06", None)
    assert first.created and not second.created and first.id == second.id
    with pytest.raises(RunConflict) as conflict:
        await create(None, [aapl])
    assert conflict.value.run_id == first.id
    async with db.transaction() as session:
        claimed = await claim_next(session)
    assert claimed is not None and claimed.id == first.id
