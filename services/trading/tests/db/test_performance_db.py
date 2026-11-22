"""A-NFR-01 on a real trading_db: the persisted run over 40 instruments and 252 sessions
(one transaction per session, with the orders, fills, state, values and outbox written in
it) finishes in under 60 s. Runs in Jenkins on the build agent."""

import json
import time
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from pydantic import SecretStr
from sqlalchemy import func, select, text
from trading_db_support import TradingDb, migrated_database, run

from qs_template import Database
from qs_trading.adapters.file_environment import FileEnvironment
from qs_trading.demo import benchmark
from qs_trading.engine.runner import run_portfolio
from qs_trading.engine.store import PortfolioStore
from qs_trading.models import portfolio_state_current, portfolio_value
from qs_trading.models import trade_event as log
from qs_trading.settings import TradingSettings

pytestmark = pytest.mark.db

BUDGET_SECONDS = 60.0
# The run tests/unit/test_performance.py times in memory
MOMENTUM = {"lookback": 60, "top_n": 10, "rebalance_every": 5, "max_position": "0.15"}
COST_MODEL = {"fixed": "1.00", "per_share": "0.005", "pct": "0.0005"}
SLIPPAGE_MODEL = {"kind": "volume", "bps": "10"}


@pytest.fixture(scope="module")
def trading_db() -> Iterator[TradingDb]:
    with migrated_database() as database:
        yield database


def _settings(url: str) -> TradingSettings:
    return TradingSettings(
        database_url=SecretStr(url),
        redis_url=SecretStr("redis://127.0.0.1:1/0"),
        content_hash="test-hash",
    )


def _jsonb(value: dict[str, Any]) -> str:
    return json.dumps(value)


async def _benchmark_portfolio(database: Database) -> uuid.UUID:
    portfolio_id = uuid.uuid4()
    async with database.transaction() as session:
        strategy_id = await session.scalar(
            text(
                "INSERT INTO strategy (name, kind, params, owner_id)"
                " VALUES ('A-NFR-01 momentum', 'momentum', CAST(:params AS jsonb),"
                " gen_random_uuid()) RETURNING id"
            ),
            {"params": _jsonb(MOMENTUM)},
        )
        await session.execute(
            text(
                "INSERT INTO portfolio (id, name, strategy_id, owner_id, initial_capital,"
                " cost_model, slippage_model, env_type, replay_environment_id)"
                " VALUES (:id, 'A-NFR-01 benchmark', :strategy, gen_random_uuid(), 1000000,"
                " CAST(:cost AS jsonb), CAST(:slippage AS jsonb), 'replay', :env)"
            ),
            {
                "id": portfolio_id,
                "strategy": strategy_id,
                "cost": _jsonb(COST_MODEL),
                "slippage": _jsonb(SLIPPAGE_MODEL),
                "env": uuid.UUID(benchmark.ENV_ID),
            },
        )
    return portfolio_id


def test_a_persisted_40_by_252_run_finishes_inside_the_budget(trading_db: TradingDb) -> None:
    async def scenario() -> None:
        database = Database(_settings(trading_db.app_url))
        try:
            portfolio_id = await _benchmark_portfolio(database)
            store = PortfolioStore(database, portfolio_id)
            spec = await store.load_spec()

            started = time.perf_counter()
            result = await run_portfolio(spec, FileEnvironment(benchmark.PATH), store)
            elapsed = time.perf_counter() - started
            print(
                f"A-NFR-01 persisted run: {benchmark.INSTRUMENTS} instruments x"
                f" {benchmark.SESSIONS} sessions, {result.final_seq} events in {elapsed:.2f} s"
            )

            async with database.transaction() as session:
                stored = await session.execute(
                    select(func.count(), func.max(log.c.seq)).where(
                        log.c.portfolio_id == portfolio_id
                    )
                )
                count, last_seq = stored.one()
                state = (
                    await session.execute(
                        select(portfolio_state_current).where(
                            portfolio_state_current.c.portfolio_id == portfolio_id
                        )
                    )
                ).one()
                values = await session.scalar(
                    select(func.count())
                    .select_from(portfolio_value)
                    .where(portfolio_value.c.portfolio_id == portfolio_id)
                )
            assert result.sessions == benchmark.SESSIONS
            assert count == last_seq == result.final_seq
            assert (state.last_seq, state.last_hash) == (result.final_seq, result.final_hash)
            assert state.last_session == benchmark.SESSIONS - 1
            assert values == benchmark.SESSIONS
            assert elapsed < BUDGET_SECONDS, f"A-NFR-01: {elapsed:.2f} s is over 60 s"
        finally:
            await database.close()

    run(scenario())
