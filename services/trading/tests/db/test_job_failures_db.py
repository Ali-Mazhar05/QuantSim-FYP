"""On a real trading_db: a run that can never succeed ends its job as failed after one
attempt while a transient failure is retried up to ``max_attempts``; the strategy kind
CHECK refuses an unknown kind; and the migrations go up, down and up again through 0003.
Every test that runs the worker has a database of its own, so it claims only its jobs."""

import shutil
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from alembic import command
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine
from trading_db_support import (
    TradingDb,
    alembic_config,
    database_url,
    fresh_database,
    migrated_database,
    run,
)

from qs_template import Database
from qs_template.jobs import JobQueue, JobState, Worker
from qs_trading.adapters.file_environment import file_environments
from qs_trading.domain.strategies import KINDS
from qs_trading.jobs import EnvironmentFactory, build_handlers, job_queue, submit_engine_run
from qs_trading.ports.market_environment import EnvironmentRef, MarketEnvironment
from qs_trading.settings import TradingSettings

pytestmark = pytest.mark.db

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/environments/two_symbols_10_sessions.json"
ENV_ID = "5d0c6c1e-7a14-4a14-8a14-000000000001"
MOMENTUM = '{"lookback": 2, "top_n": 1, "rebalance_every": 2, "max_position": "0.9"}'
MAX_ATTEMPTS = 3


def _settings(url: str) -> TradingSettings:
    return TradingSettings(
        database_url=SecretStr(url),
        redis_url=SecretStr("redis://127.0.0.1:1/0"),
        content_hash="test-hash",
        job_lease_seconds=30,
        job_max_attempts=MAX_ATTEMPTS,
    )


async def _new_portfolio(database: Database, fingerprint: str | None = None) -> uuid.UUID:
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
                " env_type, replay_environment_id, source_fingerprint)"
                " VALUES (:id, 'Hardening', :strategy, gen_random_uuid(), 10000, 'replay',"
                " :env, :fingerprint)"
            ),
            {
                "id": portfolio_id,
                "strategy": strategy_id,
                "env": uuid.UUID(ENV_ID),
                "fingerprint": fingerprint,
            },
        )
    return portfolio_id


async def _state(database: Database, queue: JobQueue, job_id: uuid.UUID) -> JobState:
    async with database.transaction() as session:
        state = await queue.get(session, job_id)
    assert state is not None
    return state


def _run_one_job(
    environments: Callable[[Path], EnvironmentFactory],
    tmp_path: Path,
    *,
    fingerprint: str | None = None,
) -> list[JobState]:
    """Submits one run on a fresh database and lets the worker claim until it has nothing
    left; the job's state after every claim."""
    states: list[JobState] = []
    with migrated_database() as trading_db:

        async def scenario() -> None:
            settings = _settings(trading_db.app_url)
            database = Database(settings)
            queue = job_queue(settings)
            try:
                portfolio_id = await _new_portfolio(database, fingerprint)
                async with database.transaction() as session:
                    submitted = await submit_engine_run(session, queue, portfolio_id)
                handlers = build_handlers(database, environments(tmp_path), queue)
                worker = Worker(database, queue, handlers)
                while await worker.run_once():
                    states.append(await _state(database, queue, submitted.id))
                    assert len(states) <= MAX_ATTEMPTS
            finally:
                await database.close()

        run(scenario())
    return states


def test_a_missing_fixture_fails_the_job_after_one_attempt(tmp_path: Path) -> None:
    # tmp_path holds no fixture for the portfolio's environment
    states = _run_one_job(file_environments, tmp_path)
    assert len(states) == 1
    final = states[0]
    assert (final.status, final.attempts) == ("failed", 1)
    assert final.error is not None and final.error.startswith("FixtureError: ")
    assert final.finished_at is not None and final.result is None


def test_a_changed_fingerprint_fails_the_job_after_one_attempt(tmp_path: Path) -> None:
    shutil.copyfile(FIXTURE, tmp_path / f"{ENV_ID}.json")
    # The portfolio already ran under other data
    states = _run_one_job(file_environments, tmp_path, fingerprint="sha256:earlier-data")
    assert [(s.status, s.attempts) for s in states] == [("failed", 1)]
    assert states[0].error is not None and states[0].error.startswith("FingerprintChanged: ")


def test_a_transient_failure_is_retried_up_to_max_attempts(tmp_path: Path) -> None:
    def flaky(_: Path) -> EnvironmentFactory:
        def open_environment(ref: EnvironmentRef) -> MarketEnvironment:
            raise ConnectionError("the feed is down for now")

        return open_environment

    states = _run_one_job(flaky, tmp_path)
    assert [(s.status, s.attempts) for s in states] == [
        ("queued", 1),
        ("queued", 2),
        ("failed", MAX_ATTEMPTS),
    ]
    assert all(s.error and s.error.startswith("ConnectionError: ") for s in states)


def test_a_transient_failure_that_clears_lets_the_retry_succeed(tmp_path: Path) -> None:
    shutil.copyfile(FIXTURE, tmp_path / f"{ENV_ID}.json")
    calls: list[EnvironmentRef] = []

    def once_down(directory: Path) -> EnvironmentFactory:
        files = file_environments(directory)

        def open_environment(ref: EnvironmentRef) -> MarketEnvironment:
            calls.append(ref)
            if len(calls) == 1:
                raise TimeoutError("the feed timed out")
            return files(ref)

        return open_environment

    states = _run_one_job(once_down, tmp_path)
    assert [(s.status, s.attempts) for s in states] == [("queued", 1), ("succeeded", 2)]
    assert states[-1].error is None and states[-1].result is not None


# --- the strategy kind CHECK (0003) ---------------------------------------------------------


@pytest.fixture(scope="module")
def trading_db() -> Iterator[TradingDb]:
    with migrated_database() as database:
        yield database


async def _insert_strategy(url: str, kind: str) -> None:
    """Inserts a strategy of ``kind`` in a transaction that is always rolled back."""
    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                await connection.execute(
                    text(
                        "INSERT INTO strategy (name, kind, owner_id)"
                        " VALUES ('Kind check', :kind, gen_random_uuid())"
                    ),
                    {"kind": kind},
                )
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()


@pytest.mark.parametrize("kind", KINDS)
def test_every_built_in_kind_is_accepted(trading_db: TradingDb, kind: str) -> None:
    run(_insert_strategy(trading_db.app_url, kind))


@pytest.mark.parametrize("kind", ["astrology", "momentum_v2", "a"])
def test_an_unknown_kind_is_refused(trading_db: TradingDb, kind: str) -> None:
    with pytest.raises(IntegrityError) as raised:
        run(_insert_strategy(trading_db.app_url, kind))
    assert "strategy_kind_known" in str(raised.value)


# --- migration up/down/up through 0003 ------------------------------------------------------


async def _strategy_checks(url: str) -> set[str]:
    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection:
            rows = await connection.execute(
                text(
                    "SELECT conname FROM pg_constraint"
                    " WHERE conrelid = 'strategy'::regclass AND contype = 'c'"
                )
            )
            return {row[0] for row in rows}
    finally:
        await engine.dispose()


def test_0003_reverses_to_the_format_check_and_applies_again() -> None:
    with fresh_database() as database, database_url(database.app_url):
        config = alembic_config()
        command.upgrade(config, "head")
        checks = run(_strategy_checks(database.app_url))
        assert "strategy_kind_known" in checks and "strategy_kind_format" not in checks

        command.downgrade(config, "0002")
        checks = run(_strategy_checks(database.app_url))
        assert "strategy_kind_format" in checks and "strategy_kind_known" not in checks
        # Back on 0002 any well-formed kind passes again
        run(_insert_strategy(database.app_url, "astrology"))

        command.upgrade(config, "head")
        assert "strategy_kind_known" in run(_strategy_checks(database.app_url))
        with pytest.raises(IntegrityError):
            run(_insert_strategy(database.app_url, "astrology"))

        command.downgrade(config, "base")
        command.upgrade(config, "head")
        checks = run(_strategy_checks(database.app_url))
        assert "strategy_kind_known" in checks and "strategy_kind_format" not in checks
