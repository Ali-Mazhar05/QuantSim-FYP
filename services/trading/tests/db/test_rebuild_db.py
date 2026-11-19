"""Projections, rebuild, verification and point-in-time state on a real trading_db (A15).

A run's live projections (holding_history included) equal the log folded again from
seq 1, row for row, and the rebuild reports ``identical`` with the run's final hash
(A-FR-11, A-FR-12). Projection rows changed behind the engine's back are reported by table
and row, and ``--apply`` restores them. The log itself cannot be changed (A13), so a
changed stored row is checked on a copy read back from the database, and a forged event
is appended the only way the database allows, by INSERT. The state as of a seq equals the
projection at that seq (A-FR-15)."""

import uuid
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr
from sqlalchemy import delete, func, select, text, update
from trading_db_support import TradingDb, migrated_database, run

from qs_template import Database
from qs_trading import cli
from qs_trading.adapters.file_environment import FileEnvironment
from qs_trading.engine.runner import RunResult, run_portfolio
from qs_trading.engine.store import PortfolioNotFound, PortfolioStore
from qs_trading.models import (
    fill,
    holding_history,
    order,
    portfolio_state_current,
    portfolio_value,
)
from qs_trading.projections import verify_chain
from qs_trading.projections.persist import read_log, read_projection
from qs_trading.projections.rebuild import (
    ChainBroken,
    rebuild_portfolio,
    state_as_of,
    verify_portfolio,
)
from qs_trading.settings import TradingSettings

pytestmark = pytest.mark.db

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/environments/two_symbols_10_sessions.json"
ENV_ID = "5d0c6c1e-7a14-4a14-8a14-000000000001"
MOMENTUM = '{"lookback": 2, "top_n": 1, "rebalance_every": 2, "max_position": "0.9"}'


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
                " VALUES (:id, 'A15 rebuild', :strategy, gen_random_uuid(), 10000,"
                ' CAST(\'{"fixed": "1.00", "per_share": "0.01", "pct": "0.0005"}\' AS jsonb),'
                ' CAST(\'{"kind": "volume", "bps": "20"}\' AS jsonb), \'replay\', :env)'
            ),
            {"id": portfolio_id, "strategy": strategy_id, "env": uuid.UUID(ENV_ID)},
        )
    return portfolio_id


async def _run(database: Database) -> tuple[uuid.UUID, RunResult]:
    portfolio_id = await _new_portfolio(database)
    store = PortfolioStore(database, portfolio_id)
    result = await run_portfolio(await store.load_spec(), FileEnvironment(FIXTURE), store)
    return portfolio_id, result


async def _count(database: Database, table: Any, portfolio_id: uuid.UUID) -> int:
    async with database.transaction() as session:
        query = select(func.count()).select_from(table).where(table.c.portfolio_id == portfolio_id)
        return int(await session.scalar(query) or 0)


def test_a_run_rebuilds_identical_with_its_final_hash(trading_db: TradingDb) -> None:
    async def scenario() -> None:
        database = Database(_settings(trading_db.app_url))
        try:
            portfolio_id, result = await _run(database)
            fills = await _count(database, fill, portfolio_id)
            assert fills > 0
            assert await _count(database, holding_history, portfolio_id) == fills

            async with database.transaction() as session:
                rebuilt = await rebuild_portfolio(session, portfolio_id)
                report = await verify_portfolio(session, portfolio_id)
            assert rebuilt.status == "identical", rebuilt.to_json()
            assert rebuilt.differences == () and not rebuilt.applied
            assert (rebuilt.final_seq, rebuilt.final_hash) == (result.final_seq, result.final_hash)
            assert report.valid
            assert (report.last_seq, report.last_hash) == (result.final_seq, result.final_hash)

            # Applying an identical rebuild writes nothing and stays identical
            async with database.transaction() as session:
                again = await rebuild_portfolio(session, portfolio_id, apply=True)
            assert again.identical and not again.applied
        finally:
            await database.close()

    run(scenario())


def test_changed_projection_rows_are_named_and_apply_restores_them(trading_db: TradingDb) -> None:
    async def scenario() -> None:
        database = Database(_settings(trading_db.app_url))
        try:
            portfolio_id, result = await _run(database)
            async with database.transaction() as session:
                before = await read_projection(session, portfolio_id)
                fill_seq = min(before.fills)
                holding = min(before.holdings)
                value_seq = max(before.values)
                order_id = next(k for k, o in before.orders.items() if o["status"] == "filled")
                # The projections are the service role's own tables: it may change them,
                # which is exactly what the rebuild is there to catch
                mine = [fill, holding_history, portfolio_value, order, portfolio_state_current]
                f, h, v, o, st = (table.c for table in mine)
                for statement in (
                    update(fill)
                    .where(f.portfolio_id == portfolio_id, f.seq == fill_seq)
                    .values(cash_after=f.cash_after + 1),
                    delete(holding_history).where(
                        h.portfolio_id == portfolio_id, h.seq == holding[0]
                    ),
                    update(portfolio_value)
                    .where(v.portfolio_id == portfolio_id, v.seq == value_seq)
                    .values(value=v.value + 1),
                    update(order)
                    .where(o.portfolio_id == portfolio_id, o.order_id == order_id)
                    .values(status="expired"),
                    update(portfolio_state_current)
                    .where(st.portfolio_id == portfolio_id)
                    .values(cash=st.cash + 1),
                ):
                    await session.execute(statement)

            async with database.transaction() as session:
                found = await rebuild_portfolio(session, portfolio_id)
            assert found.status == "differs" and not found.applied
            assert found.final_hash == result.final_hash
            tables = {d.table: d for d in found.differences}
            assert set(tables) == {
                "order",
                "fill",
                "holding_history",
                "portfolio_value",
                "portfolio_state_current",
            }
            assert tables["fill"].changed == (f"seq={fill_seq} (cash_after)",)
            assert tables["holding_history"].missing == (f"seq={holding[0]} symbol={holding[1]}",)
            assert tables["portfolio_value"].changed == (f"seq={value_seq} (value)",)
            assert tables["order"].changed == (f"order_id={order_id} (status)",)
            assert tables["portfolio_state_current"].changed == ("state (cash)",)

            # Without --apply nothing was written
            async with database.transaction() as session:
                still = await rebuild_portfolio(session, portfolio_id)
            assert still.differences == found.differences

            async with database.transaction() as session:
                applied = await rebuild_portfolio(session, portfolio_id, apply=True)
            assert applied.applied and applied.status == "differs"
            async with database.transaction() as session:
                restored = await rebuild_portfolio(session, portfolio_id)
                after = await read_projection(session, portfolio_id)
            assert restored.identical
            assert after == before
        finally:
            await database.close()

    run(scenario())


def test_a_changed_stored_row_is_reported_at_its_seq(trading_db: TradingDb) -> None:
    async def scenario() -> None:
        database = Database(_settings(trading_db.app_url))
        try:
            portfolio_id, _ = await _run(database)
            async with database.transaction() as session:
                log = await read_log(session, portfolio_id)
            assert verify_chain(portfolio_id, log).valid
            # A copy of the stored rows with one payload changed, as if the guard had failed
            index = next(i for i, e in enumerate(log) if e.type == "ORDER_FILLED")
            payload = {**log[index].payload, "quantity": log[index].payload["quantity"] + 1}
            copy = [*log[:index], replace(log[index], payload=payload), *log[index + 1 :]]
            report = verify_chain(portfolio_id, copy)
            assert report.broken_seq == log[index].seq
            assert report.last_seq == log[index].seq - 1
        finally:
            await database.close()

    run(scenario())


def test_a_forged_appended_event_breaks_verify_and_rebuild(trading_db: TradingDb) -> None:
    async def scenario() -> None:
        database = Database(_settings(trading_db.app_url))
        try:
            portfolio_id, result = await _run(database)
            # INSERT is the one write the log takes; a row that does not chain is refused
            # by the verification, not by the database
            async with database.transaction() as session:
                await session.execute(
                    text(
                        "INSERT INTO trade_event (portfolio_id, seq, event_time, type, version,"
                        " payload, prev_hash, hash) VALUES (:p, :s, now(), 'RUN_COMPLETED', 1,"
                        ' CAST(\'{"sessions": 1, "final_value": "1.00"}\' AS jsonb), :prev,'
                        " :hash)"
                    ),
                    {
                        "p": portfolio_id,
                        "s": result.final_seq + 1,
                        "prev": result.final_hash,
                        "hash": "0" * 64,
                    },
                )
            async with database.transaction() as session:
                report = await verify_portfolio(session, portfolio_id)
            assert not report.valid
            assert report.broken_seq == result.final_seq + 1
            assert report.last_hash == result.final_hash
            with pytest.raises(ChainBroken) as broken:
                async with database.transaction() as session:
                    await rebuild_portfolio(session, portfolio_id, apply=True)
            assert broken.value.report == report
            # The intact prefix still answers point-in-time reads
            async with database.transaction() as session:
                snapshot = await state_as_of(session, portfolio_id, result.final_seq)
            assert snapshot.hash == result.final_hash
        finally:
            await database.close()

    run(scenario())


def test_the_state_as_of_a_seq_equals_the_projection_there(trading_db: TradingDb) -> None:
    async def scenario() -> None:
        database = Database(_settings(trading_db.app_url))
        try:
            portfolio_id, result = await _run(database)
            async with database.transaction() as session:
                stored = (
                    await session.execute(
                        select(portfolio_state_current).where(
                            portfolio_state_current.c.portfolio_id == portfolio_id
                        )
                    )
                ).one()
                final = await state_as_of(session, portfolio_id, result.final_seq)
                values = (
                    await session.execute(
                        select(portfolio_value)
                        .where(portfolio_value.c.portfolio_id == portfolio_id)
                        .order_by(portfolio_value.c.seq)
                    )
                ).all()
                at_values = [await state_as_of(session, portfolio_id, v.seq) for v in values]
                with pytest.raises(LookupError):
                    await state_as_of(session, portfolio_id, result.final_seq + 1)
                with pytest.raises(PortfolioNotFound):
                    await state_as_of(session, uuid.uuid4(), 1)
            row = dict(stored._mapping)
            del row["updated_at"]
            assert final.state_row() == row
            for snapshot, value in zip(at_values, values, strict=True):
                assert (snapshot.cash, snapshot.last_value) == (value.cash, value.value)
                assert snapshot.session == value.session
        finally:
            await database.close()

    run(scenario())


def test_an_empty_portfolio_rebuilds_identical_and_unknown_ones_are_refused(
    trading_db: TradingDb,
) -> None:
    async def scenario() -> None:
        database = Database(_settings(trading_db.app_url))
        try:
            portfolio_id = await _new_portfolio(database)
            async with database.transaction() as session:
                empty = await rebuild_portfolio(session, portfolio_id, apply=True)
                with pytest.raises(PortfolioNotFound):
                    await rebuild_portfolio(session, uuid.uuid4())
            assert empty.identical and (empty.final_seq, empty.final_hash) == (0, None)
        finally:
            await database.close()

    run(scenario())


def test_the_rebuild_command_runs_against_the_database(
    trading_db: TradingDb, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    async def prepare() -> tuple[uuid.UUID, RunResult]:
        database = Database(_settings(trading_db.app_url))
        try:
            return await _run(database)
        finally:
            await database.close()

    portfolio_id, result = run(prepare())
    monkeypatch.setenv("QS_DATABASE_URL", trading_db.app_url)
    monkeypatch.setenv("QS_REDIS_URL", "redis://127.0.0.1:1/0")
    for command in (["verify", str(portfolio_id)], ["rebuild", str(portfolio_id)]):
        with pytest.raises(SystemExit) as stopped:
            cli.main(command)
        assert stopped.value.code == 0
        assert result.final_hash in capsys.readouterr().out
