"""The engine run persisted to a real trading_db (A14): a gap-free chained log whose
stored rows still hash to themselves, the state row and the outbox written with it, crash
resume to an identical log (A-FR-13) and an idempotent run submit (K1)."""

import shutil
import uuid
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr
from sqlalchemy import func, select, text
from trading_db_support import TradingDb, migrated_database, run

from qs_template import Database
from qs_template.jobs import Worker
from qs_template.messaging import outbox
from qs_trading.adapters.file_environment import FileEnvironment, file_environments
from qs_trading.domain.hashing import event_hash
from qs_trading.engine.core import Engine
from qs_trading.engine.runner import load_ticks, run_portfolio
from qs_trading.engine.store import ChainConflict, PortfolioStore
from qs_trading.jobs import ENGINE_RUN, build_handlers, job_queue, submit_engine_run
from qs_trading.models import fill, order, portfolio, portfolio_state_current, portfolio_value
from qs_trading.models import trade_event as log
from qs_trading.settings import TradingSettings

pytestmark = pytest.mark.db

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/environments/two_symbols_10_sessions.json"
ENV_ID = "5d0c6c1e-7a14-4a14-8a14-000000000001"
SESSIONS = 10
MOMENTUM = '{"lookback": 2, "top_n": 1, "rebalance_every": 2, "max_position": "0.9"}'


class Crash(Exception):
    """Stands in for a killed worker."""


@pytest.fixture(scope="module")
def trading_db() -> Iterator[TradingDb]:
    with migrated_database() as database:
        yield database


def _settings(url: str) -> TradingSettings:
    return TradingSettings(
        database_url=SecretStr(url),
        redis_url=SecretStr("redis://127.0.0.1:1/0"),
        content_hash="test-hash",
        job_lease_seconds=30,
    )


async def _new_portfolio(database: Database) -> uuid.UUID:
    portfolio_id = uuid.uuid4()
    async with database.transaction() as session:
        strategy_id = await session.scalar(
            text(
                "INSERT INTO strategy (name, kind, params, owner_id)"
                " VALUES ('Momentum 2', 'momentum', CAST(:params AS jsonb), gen_random_uuid())"
                " RETURNING id"
            ),
            {"params": MOMENTUM},
        )
        await session.execute(
            text(
                "INSERT INTO portfolio (id, name, strategy_id, owner_id, initial_capital,"
                " cost_model, slippage_model, env_type, replay_environment_id)"
                " VALUES (:id, 'A14 engine', :strategy, gen_random_uuid(), 10000,"
                ' CAST(\'{"fixed": "1.00", "per_share": "0.01", "pct": "0.0005"}\' AS jsonb),'
                ' CAST(\'{"kind": "volume", "bps": "20"}\' AS jsonb), \'replay\', :env)'
            ),
            {"id": portfolio_id, "strategy": strategy_id, "env": uuid.UUID(ENV_ID)},
        )
    return portfolio_id


async def _expected_hashes(store: PortfolioStore) -> list[str]:
    """The same portfolio's run computed in memory, never interrupted."""
    environment = FileEnvironment(FIXTURE)
    fingerprint = await environment.activate()
    spec = await store.load_spec()
    engine = Engine.prepare(spec, fingerprint, await load_ticks(environment, fingerprint))
    return [event.hash for result in engine.run() for event in result.events]


async def _stored_log(database: Database, portfolio_id: uuid.UUID) -> list[Any]:
    async with database.transaction() as session:
        rows = await session.execute(
            select(log).where(log.c.portfolio_id == portfolio_id).order_by(log.c.seq)
        )
        return list(rows)


async def _count(database: Database, table: Any, portfolio_id: uuid.UUID, **where: Any) -> int:
    async with database.transaction() as session:
        query = select(func.count()).select_from(table).where(table.c.portfolio_id == portfolio_id)
        for column, value in where.items():
            query = query.where(table.c[column] == value)
        return int(await session.scalar(query) or 0)


async def _outbox_types(database: Database, portfolio_id: uuid.UUID) -> list[str]:
    async with database.transaction() as session:
        rows = await session.execute(
            select(outbox.c.event_type)
            .where(outbox.c.message_key == str(portfolio_id))
            .order_by(outbox.c.id)
        )
        return [row[0] for row in rows]


def _assert_chained_and_self_hashing(rows: list[Any], portfolio_id: uuid.UUID) -> None:
    previous: str | None = None
    for expected_seq, row in enumerate(rows, start=1):
        assert row.seq == expected_seq
        assert row.prev_hash == previous
        # The stored JSONB payload and timestamptz hash back to the stored hash
        assert row.hash == event_hash(
            previous,
            portfolio_id=portfolio_id,
            seq=row.seq,
            event_type=row.type,
            version=row.version,
            payload=row.payload,
            event_time=row.event_time,
        )
        previous = row.hash


def test_a_run_persists_a_chained_log_with_its_state_and_outbox(trading_db: TradingDb) -> None:
    async def scenario() -> None:
        database = Database(_settings(trading_db.app_url))
        try:
            portfolio_id = await _new_portfolio(database)
            store = PortfolioStore(database, portfolio_id)
            result = await run_portfolio(await store.load_spec(), FileEnvironment(FIXTURE), store)

            rows = await _stored_log(database, portfolio_id)
            _assert_chained_and_self_hashing(rows, portfolio_id)
            assert [row.hash for row in rows] == await _expected_hashes(store)
            assert (rows[0].type, rows[-1].type) == ("RUN_STARTED", "RUN_COMPLETED")
            assert (result.final_seq, result.final_hash) == (rows[-1].seq, rows[-1].hash)

            async with database.transaction() as session:
                state = (
                    await session.execute(
                        select(portfolio_state_current).where(
                            portfolio_state_current.c.portfolio_id == portfolio_id
                        )
                    )
                ).one()
                bound = await session.scalar(
                    select(portfolio.c.source_fingerprint).where(portfolio.c.id == portfolio_id)
                )
            assert (state.last_seq, state.last_hash) == (result.final_seq, result.final_hash)
            assert state.last_session == SESSIONS - 1
            assert bound == result.source_fingerprint

            fills = sum(row.type == "ORDER_FILLED" for row in rows)
            placed = sum(row.type == "ORDER_PLACED" for row in rows)
            assert fills > 0
            assert await _count(database, fill, portfolio_id) == fills
            assert await _count(database, order, portfolio_id) == placed
            assert await _count(database, order, portfolio_id, status="filled") == fills
            assert await _count(database, portfolio_value, portfolio_id) == SESSIONS
            types = await _outbox_types(database, portfolio_id)
            assert types.count("fill.executed") == fills
            assert types.count("portfolio.updated") == SESSIONS
            assert types[-1] == "run.completed" and types.count("run.completed") == 1

            # A second writer chaining onto an old head is refused, and nothing changes
            environment = FileEnvironment(FIXTURE)
            fingerprint = await environment.activate()
            engine = Engine.prepare(
                await store.load_spec(), fingerprint, await load_ticks(environment, fingerprint)
            )
            with pytest.raises(ChainConflict):
                await store.commit(engine, engine.run()[0])
            assert len(await _stored_log(database, portfolio_id)) == len(rows)
        finally:
            await database.close()

    run(scenario())


@pytest.mark.parametrize("crash_after", [1, SESSIONS // 2, SESSIONS - 1])
def test_a_crash_then_resume_gives_the_identical_log(
    trading_db: TradingDb, crash_after: int
) -> None:
    async def scenario() -> None:
        database = Database(_settings(trading_db.app_url))
        try:
            portfolio_id = await _new_portfolio(database)
            store = PortfolioStore(database, portfolio_id)

            async def killed(share: float) -> None:
                if round(share * SESSIONS) == crash_after:
                    raise Crash

            spec = await store.load_spec()
            with pytest.raises(Crash):
                await run_portfolio(spec, FileEnvironment(FIXTURE), store, progress=killed)
            head = await store.head()
            committed = await _stored_log(database, portfolio_id)
            assert committed[-1].seq == head.last_seq and committed[-1].hash == head.last_hash

            resumed = PortfolioStore(database, portfolio_id)
            result = await run_portfolio(
                await resumed.load_spec(), FileEnvironment(FIXTURE), resumed
            )
            assert result.resumed_at_session == crash_after

            rows = await _stored_log(database, portfolio_id)
            _assert_chained_and_self_hashing(rows, portfolio_id)
            assert [row.hash for row in rows] == await _expected_hashes(store)
            assert rows[: len(committed)] == committed
            types = await _outbox_types(database, portfolio_id)
            assert types.count("portfolio.updated") == SESSIONS
            assert types.count("run.completed") == 1
            fills = sum(row.type == "ORDER_FILLED" for row in rows)
            assert types.count("fill.executed") == fills
            assert await _count(database, fill, portfolio_id) == fills
        finally:
            await database.close()

    run(scenario())


def test_the_run_job_submits_once_and_runs_on_the_worker(
    trading_db: TradingDb, tmp_path: Path
) -> None:
    shutil.copyfile(FIXTURE, tmp_path / f"{ENV_ID}.json")

    async def scenario() -> None:
        settings = _settings(trading_db.app_url)
        database = Database(settings)
        queue = job_queue(settings)
        try:
            portfolio_id = await _new_portfolio(database)
            async with database.transaction() as session:
                first = await submit_engine_run(session, queue, portfolio_id)
                again = await submit_engine_run(session, queue, portfolio_id)
                keyed = await submit_engine_run(session, queue, portfolio_id, idempotency_key="k")
            assert first.created and not again.created and again.id == first.id
            assert keyed.id != first.id

            handlers = build_handlers(database, file_environments(tmp_path))
            worker = Worker(database, queue, {ENGINE_RUN: handlers[ENGINE_RUN]})
            # Both jobs share created_at (one transaction), so either may be claimed first:
            # the first runs the portfolio, the second finds the run complete
            assert await worker.run_once()
            assert await worker.run_once()
            expected = (await _expected_hashes(PortfolioStore(database, portfolio_id)))[-1]
            resumed_at: list[int] = []
            for job_id in (first.id, keyed.id):
                async with database.transaction() as session:
                    state = await queue.get(session, job_id)
                assert state is not None and state.status == "succeeded", state
                assert state.progress == 1.0 and state.result is not None
                assert state.result["final_hash"] == expected
                assert Decimal(state.result["final_value"]) > 0
                resumed_at.append(state.result["resumed_at_session"])
            assert sorted(resumed_at) == [0, SESSIONS]
            types = await _outbox_types(database, portfolio_id)
            assert types[-1] == "run.completed" and types.count("run.completed") == 1
        finally:
            await database.close()

    run(scenario())
