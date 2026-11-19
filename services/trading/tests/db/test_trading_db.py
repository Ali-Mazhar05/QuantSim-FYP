"""trading_db built by the migrations on a real PostgreSQL + TimescaleDB, set up the way
db-init sets up deployed environments: the database is owned by a login role of its own,
the superuser creates the timescaledb extension, and the migrations run as that role.

Covers A-FR-04 (the binding CHECK) and A-FR-10 (UPDATE and DELETE on the trade log fail
for the service's role and for the owner, a repeated (portfolio, seq) fails, gaps fail),
the money and order CHECKs, and migration up/down/up."""

import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import MetaData, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine
from trading_db_support import (
    TradingDb,
    run,
)
from trading_db_support import alembic_config as _alembic_config
from trading_db_support import database_url as _database_url
from trading_db_support import fresh_database as _fresh_database

from qs_template.messaging import messaging_metadata
from qs_trading import models

pytestmark = pytest.mark.db

NEW_TABLES = {
    "strategy",
    "portfolio",
    "order",
    "fill",
    "trade_event",
    "holding_history",
    "portfolio_value",
    "portfolio_metrics",
    "portfolio_state_current",
    "instrument_ref",
}
NEW_FUNCTIONS = {"qs_trading_append_only", "qs_trade_event_seq_follows"}
START = datetime(2026, 1, 5, 21, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def trading_db() -> Iterator[TradingDb]:
    with _fresh_database() as database, _database_url(database.app_url):
        command.upgrade(_alembic_config(), "head")
        yield database


async def _with_connection(url: str, work: Callable[[AsyncConnection], Any]) -> Any:
    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection:
            return await work(connection)
    finally:
        await engine.dispose()


def _rolled_back(url: str, work: Callable[[AsyncConnection], Any]) -> Any:
    """Run ``work`` in a transaction that is always rolled back; return its result."""

    async def wrapped(connection: AsyncConnection) -> Any:
        transaction = await connection.begin()
        try:
            return await work(connection)
        finally:
            await transaction.rollback()

    return run(_with_connection(url, wrapped))


def _refused(url: str, attempt: Callable[[AsyncConnection], Any]) -> DBAPIError:
    """Run ``attempt`` in a rolled-back transaction; return the database's refusal."""

    async def work(connection: AsyncConnection) -> DBAPIError:
        try:
            await attempt(connection)
        except DBAPIError as error:
            return error
        raise AssertionError("the database accepted something it must refuse")

    error: DBAPIError = _rolled_back(url, work)
    return error


# --- rows -------------------------------------------------------------------------------


async def _insert_strategy(connection: AsyncConnection) -> uuid.UUID:
    strategy_id = uuid.uuid4()
    await connection.execute(
        text(
            "INSERT INTO strategy (id, name, kind, params, owner_id)"
            " VALUES (:id, 'Momentum 20', 'momentum', CAST('{\"lookback\": 20}' AS jsonb),"
            " :owner)"
        ),
        {"id": strategy_id, "owner": uuid.uuid4()},
    )
    return strategy_id


async def _insert_portfolio(connection: AsyncConnection, **overrides: Any) -> uuid.UUID:
    values: dict[str, Any] = {
        "id": uuid.uuid4(),
        "capital": "100000.00",
        "currency": "USD",
        "env_type": "replay",
        "replay": uuid.uuid4(),
        "simulation": None,
        "path_index": None,
    }
    values.update(overrides)
    values["strategy"] = await _insert_strategy(connection)
    await connection.execute(
        text(
            "INSERT INTO portfolio (id, name, strategy_id, owner_id, initial_capital,"
            " base_currency, cost_model, slippage_model, env_type, replay_environment_id,"
            " simulation_run_id, path_index, source_fingerprint)"
            " VALUES (:id, 'Tech momentum', :strategy, gen_random_uuid(), :capital, :currency,"
            ' CAST(\'{"fixed": "1.00"}\' AS jsonb), CAST(\'{"bps": "5"}\' AS jsonb),'
            " :env_type, :replay, :simulation, :path_index, 'sha256:abc')"
        ),
        values,
    )
    portfolio_id: uuid.UUID = values["id"]
    return portfolio_id


async def _append(
    connection: AsyncConnection,
    portfolio_id: uuid.UUID,
    seq: int,
    *,
    event_time: datetime | None = None,
    event_type: str = "TICK",
) -> None:
    await connection.execute(
        text(
            "INSERT INTO trade_event (portfolio_id, seq, event_time, type, version, payload,"
            " prev_hash, hash)"
            " VALUES (:portfolio, :seq, :event_time, :type, 1, CAST('{}' AS jsonb),"
            " :prev_hash, :hash)"
        ),
        {
            "portfolio": portfolio_id,
            "seq": seq,
            "event_time": event_time or START + timedelta(days=seq),
            "type": event_type,
            "prev_hash": None if seq == 1 else f"h{seq - 1}",
            "hash": f"h{seq}",
        },
    )


async def _portfolio_with_events(connection: AsyncConnection, count: int = 3) -> uuid.UUID:
    portfolio_id = await _insert_portfolio(connection)
    for seq in range(1, count + 1):
        await _append(connection, portfolio_id, seq)
    return portfolio_id


async def _insert_order(connection: AsyncConnection, **overrides: Any) -> uuid.UUID:
    portfolio_id = await _insert_portfolio(connection)
    values: dict[str, Any] = {
        "portfolio": portfolio_id,
        "order_id": "o-1",
        "quantity": 10,
        "order_type": "limit",
        "limit_price": "187.12345678",
        "expires": 5,
        "status": "open",
    }
    values.update(overrides)
    await connection.execute(
        text(
            'INSERT INTO "order" (portfolio_id, order_id, symbol, side, quantity, order_type,'
            " limit_price, placed_seq, placed_session, expires_session, status)"
            " VALUES (:portfolio, :order_id, 'AAPL', 'buy', :quantity, :order_type,"
            " :limit_price, 2, 1, :expires, :status)"
        ),
        values,
    )
    return portfolio_id


async def _insert_fill(connection: AsyncConnection, **costs: Any) -> None:
    portfolio_id = await _insert_order(connection)
    values: dict[str, Any] = {
        "portfolio": portfolio_id,
        "order_id": "o-1",
        "fixed": "1.00",
        "per_share": "0.05",
        "percentage": "0.94",
        "total": "1.99",
    }
    values.update(costs)
    await connection.execute(
        text(
            "INSERT INTO fill (portfolio_id, seq, order_id, session, symbol, side, quantity,"
            " reference_price, fill_price, slippage, cost_fixed, cost_per_share,"
            " cost_percentage, cost_total, cash_after)"
            " VALUES (:portfolio, 3, :order_id, 2, 'AAPL', 'buy', 10, 187.10000000,"
            " 187.19355000, 0.09355000, :fixed, :per_share, :percentage, :total, 98126.08)"
        ),
        values,
    )


async def _insert_state(connection: AsyncConnection, cash: str) -> None:
    portfolio_id = await _insert_portfolio(connection)
    await connection.execute(
        text(
            "INSERT INTO portfolio_state_current (portfolio_id, last_seq, last_hash, cash,"
            " positions) VALUES (:portfolio, 4, 'h4', :cash, CAST('{\"AAPL\": 10}' AS jsonb))"
        ),
        {"portfolio": portfolio_id, "cash": cash},
    )


# --- schema -----------------------------------------------------------------------------


def _combined_metadata() -> MetaData:
    combined = MetaData()
    for source in (models.metadata, messaging_metadata):
        for table in source.tables.values():
            table.to_metadata(combined)
    return combined


def _diff(connection: Connection) -> list[Any]:
    context = MigrationContext.configure(connection, opts={"compare_type": True})
    return list(compare_metadata(context, _combined_metadata()))


def test_models_match_the_migrations_exactly(trading_db: TradingDb) -> None:
    async def work(connection: AsyncConnection) -> list[Any]:
        return await connection.run_sync(_diff)

    assert run(_with_connection(trading_db.app_url, work)) == []


def test_the_log_and_the_value_series_are_hypertables(trading_db: TradingDb) -> None:
    async def work(connection: AsyncConnection) -> set[str]:
        rows = await connection.execute(
            text("SELECT hypertable_name FROM timescaledb_information.hypertables")
        )
        return {row[0] for row in rows}

    assert run(_with_connection(trading_db.app_url, work)) == {"trade_event", "portfolio_value"}


def test_a_valid_log_is_accepted_and_reads_back_in_order(trading_db: TradingDb) -> None:
    async def work(connection: AsyncConnection) -> list[tuple[int, str]]:
        portfolio_id = await _portfolio_with_events(connection, count=4)
        rows = await connection.execute(
            text("SELECT seq, hash FROM trade_event WHERE portfolio_id = :p ORDER BY seq"),
            {"p": portfolio_id},
        )
        return [(row[0], row[1]) for row in rows]

    assert _rolled_back(trading_db.app_url, work) == [(1, "h1"), (2, "h2"), (3, "h3"), (4, "h4")]


def test_events_appended_in_one_statement_must_still_follow_each_other(
    trading_db: TradingDb,
) -> None:
    async def work(connection: AsyncConnection) -> int:
        portfolio_id = await _insert_portfolio(connection)
        await connection.execute(
            text(
                "INSERT INTO trade_event (portfolio_id, seq, event_time, type, payload,"
                " prev_hash, hash) SELECT CAST(:p AS uuid), s,"
                " CAST(:start AS timestamptz) + make_interval(days => s),"
                " 'TICK', CAST('{}' AS jsonb), CASE WHEN s > 1 THEN 'h' END, 'h'"
                " FROM generate_series(1, 5) AS s"
            ),
            {"p": portfolio_id, "start": START},
        )
        count: int = await connection.scalar(
            text("SELECT count(*) FROM trade_event WHERE portfolio_id = :p"), {"p": portfolio_id}
        )
        return count

    assert _rolled_back(trading_db.app_url, work) == 5


# --- the trade log is append-only (A-FR-10) ---------------------------------------------

TAMPERING = {
    "update": "UPDATE trade_event SET hash = 'forged'",
    "delete": "DELETE FROM trade_event",
}


@pytest.mark.parametrize("statement", TAMPERING.values(), ids=TAMPERING.keys())
def test_the_service_role_may_not_change_the_log(trading_db: TradingDb, statement: str) -> None:
    async def attempt(connection: AsyncConnection) -> None:
        await _portfolio_with_events(connection)
        await connection.execute(text(statement))

    error = _refused(trading_db.app_url, attempt)
    assert "permission denied" in str(error)


@pytest.mark.parametrize("statement", TAMPERING.values(), ids=TAMPERING.keys())
def test_the_guard_trigger_stops_the_owner_even_with_the_privilege_granted_back(
    trading_db: TradingDb, statement: str
) -> None:
    async def attempt(connection: AsyncConnection) -> None:
        owner = await connection.scalar(
            text("SELECT tableowner FROM pg_tables WHERE tablename = 'trade_event'")
        )
        assert owner == trading_db.role
        await _portfolio_with_events(connection)
        await connection.execute(text("GRANT UPDATE, DELETE ON trade_event TO CURRENT_USER"))
        await connection.execute(text(statement))

    error = _refused(trading_db.app_url, attempt)
    assert "trade_event is append-only" in str(error)


@pytest.mark.parametrize("statement", TAMPERING.values(), ids=TAMPERING.keys())
def test_the_guard_trigger_stops_a_superuser(trading_db: TradingDb, statement: str) -> None:
    async def attempt(connection: AsyncConnection) -> None:
        await _portfolio_with_events(connection)
        await connection.execute(text(statement))

    error = _refused(trading_db.admin_url, attempt)
    assert "trade_event is append-only" in str(error)


def test_the_service_role_may_still_append_and_read(trading_db: TradingDb) -> None:
    async def work(connection: AsyncConnection) -> list[str]:
        rows = await connection.execute(
            text(
                "SELECT privilege_type FROM information_schema.role_table_grants"
                " WHERE table_name = 'trade_event' AND grantee = current_user"
            )
        )
        return sorted(row[0] for row in rows)

    granted = run(_with_connection(trading_db.app_url, work))
    assert {"INSERT", "SELECT"} <= set(granted)
    assert not {"UPDATE", "DELETE", "TRUNCATE"} & set(granted)


def test_a_repeated_portfolio_seq_is_refused_even_at_another_time(trading_db: TradingDb) -> None:
    async def attempt(connection: AsyncConnection) -> None:
        portfolio_id = await _portfolio_with_events(connection)
        # A different event_time would satisfy the hypertable's primary key on its own
        await _append(connection, portfolio_id, 2, event_time=START + timedelta(days=400))

    error = _refused(trading_db.app_url, attempt)
    assert isinstance(error, IntegrityError)
    assert "trade_event_seq_unique" in str(error)


@pytest.mark.parametrize(("existing", "seq"), [(0, 2), (3, 5)], ids=["first-not-1", "gap"])
def test_a_gap_in_the_log_is_refused(trading_db: TradingDb, existing: int, seq: int) -> None:
    async def attempt(connection: AsyncConnection) -> None:
        portfolio_id = await _portfolio_with_events(connection, count=existing)
        await _append(connection, portfolio_id, seq)

    error = _refused(trading_db.app_url, attempt)
    assert isinstance(error, IntegrityError)
    assert "trade_event_seq_gap_free" in str(error)


def test_each_portfolio_counts_its_own_seq(trading_db: TradingDb) -> None:
    async def work(connection: AsyncConnection) -> int:
        await _portfolio_with_events(connection)
        other = await _portfolio_with_events(connection, count=1)
        await _append(connection, other, 2)
        count: int = await connection.scalar(text("SELECT count(*) FROM trade_event"))
        return count

    assert _rolled_back(trading_db.app_url, work) == 5


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        ({"event_type": "ORDER_CANCELLED"}, "trade_event_type_valid"),
        ({}, "trade_event_chained"),
    ],
    ids=["unknown-type", "unchained"],
)
def test_malformed_events_are_refused(
    trading_db: TradingDb, overrides: dict[str, Any], constraint: str
) -> None:
    async def attempt(connection: AsyncConnection) -> None:
        portfolio_id = await _portfolio_with_events(connection, count=1)
        if constraint == "trade_event_chained":
            await connection.execute(
                text(
                    "INSERT INTO trade_event (portfolio_id, seq, event_time, type, payload,"
                    " prev_hash, hash) VALUES (:p, 2, :t, 'TICK', CAST('{}' AS jsonb),"
                    " NULL, 'h2')"
                ),
                {"p": portfolio_id, "t": START + timedelta(days=2)},
            )
        else:
            await _append(connection, portfolio_id, 2, **overrides)

    error = _refused(trading_db.app_url, attempt)
    assert constraint in str(error)


def test_holdings_rows_never_change(trading_db: TradingDb) -> None:
    async def attempt(connection: AsyncConnection) -> None:
        portfolio_id = await _insert_portfolio(connection)
        await connection.execute(
            text(
                "INSERT INTO holding_history (portfolio_id, seq, symbol, session, quantity,"
                " cost_basis) VALUES (:p, 3, 'AAPL', 2, 10, 1871.94)"
            ),
            {"p": portfolio_id},
        )
        await connection.execute(text("UPDATE holding_history SET quantity = 11"))

    error = _refused(trading_db.admin_url, attempt)
    assert "holding_history is append-only" in str(error)


# --- portfolio binding (A-FR-04) ----------------------------------------------------------


@pytest.mark.parametrize(
    "overrides",
    [
        {"env_type": "replay"},
        {"env_type": "simulation", "simulation": uuid.uuid4(), "path_index": 7},
    ],
    ids=["replay", "simulation-path"],
)
def test_a_portfolio_bound_to_exactly_one_environment_is_accepted(
    trading_db: TradingDb, overrides: dict[str, Any]
) -> None:
    if overrides["env_type"] == "simulation":
        overrides = {**overrides, "replay": None}

    async def work(connection: AsyncConnection) -> int:
        await _insert_portfolio(connection, **overrides)
        count: int = await connection.scalar(text("SELECT count(*) FROM portfolio"))
        return count

    assert _rolled_back(trading_db.app_url, work) == 1


@pytest.mark.parametrize(
    "overrides",
    [
        {"env_type": "replay", "replay": None},
        {"env_type": "simulation", "replay": None, "simulation": None, "path_index": None},
        {"env_type": "replay", "simulation": uuid.uuid4(), "path_index": 0},
        {"env_type": "simulation", "simulation": uuid.uuid4(), "path_index": 0},
        {"env_type": "replay", "path_index": 0},
        {"env_type": "simulation", "replay": None, "simulation": uuid.uuid4()},
    ],
    ids=[
        "neither-replay",
        "neither-simulation",
        "both-as-replay",
        "both-as-simulation",
        "replay-with-path",
        "simulation-without-path",
    ],
)
def test_a_portfolio_bound_to_neither_or_both_environments_is_refused(
    trading_db: TradingDb, overrides: dict[str, Any]
) -> None:
    async def attempt(connection: AsyncConnection) -> None:
        await _insert_portfolio(connection, **overrides)

    error = _refused(trading_db.app_url, attempt)
    assert isinstance(error, IntegrityError)
    assert "portfolio_environment_binding" in str(error)


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        ({"capital": "0.00"}, "portfolio_capital_positive"),
        ({"capital": "-1.00"}, "portfolio_capital_positive"),
        ({"currency": "EUR"}, "portfolio_base_currency_usd"),
        ({"env_type": "live"}, "portfolio_env_type_valid"),
    ],
)
def test_invalid_portfolios_are_refused(
    trading_db: TradingDb, overrides: dict[str, Any], constraint: str
) -> None:
    async def attempt(connection: AsyncConnection) -> None:
        await _insert_portfolio(connection, **overrides)

    error = _refused(trading_db.app_url, attempt)
    assert constraint in str(error)


# --- orders, fills and state ------------------------------------------------------------


@pytest.mark.parametrize(
    "overrides",
    [{}, {"order_type": "market", "limit_price": None, "expires": None}],
    ids=["limit", "market"],
)
def test_valid_orders_are_accepted(trading_db: TradingDb, overrides: dict[str, Any]) -> None:
    async def work(connection: AsyncConnection) -> str | None:
        await _insert_order(connection, **overrides)
        value: str | None = await connection.scalar(text('SELECT limit_price::text FROM "order"'))
        return value

    expected = None if overrides else "187.12345678"
    assert _rolled_back(trading_db.app_url, work) == expected


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        ({"limit_price": None}, "order_limit_price_iff_limit"),
        ({"order_type": "market", "expires": None}, "order_limit_price_iff_limit"),
        ({"order_type": "market", "limit_price": None}, "order_market_never_expires"),
        ({"limit_price": "0"}, "order_limit_price_positive"),
        ({"quantity": 0}, "order_quantity_positive"),
        ({"quantity": -5}, "order_quantity_positive"),
        ({"status": "cancelled"}, "order_status_valid"),
    ],
    ids=[
        "limit-without-price",
        "market-with-price",
        "market-with-expiry",
        "zero-limit-price",
        "zero-quantity",
        "negative-quantity",
        "unknown-status",
    ],
)
def test_invalid_orders_are_refused(
    trading_db: TradingDb, overrides: dict[str, Any], constraint: str
) -> None:
    async def attempt(connection: AsyncConnection) -> None:
        await _insert_order(connection, **overrides)

    error = _refused(trading_db.app_url, attempt)
    assert constraint in str(error)


def test_a_fill_whose_costs_add_up_is_accepted(trading_db: TradingDb) -> None:
    async def work(connection: AsyncConnection) -> str:
        await _insert_fill(connection)
        value: str = await connection.scalar(text("SELECT cost_total::text FROM fill"))
        return value

    assert _rolled_back(trading_db.app_url, work) == "1.99"


@pytest.mark.parametrize(
    ("costs", "constraint"),
    [
        ({"fixed": "-1.00", "total": "-0.01"}, "fill_cost_non_negative"),
        ({"total": "2.00"}, "fill_cost_adds_up"),
        ({"order_id": "o-unknown"}, "fill_order_fk"),
    ],
    ids=["negative-cost", "total-not-the-sum", "unknown-order"],
)
def test_invalid_fills_are_refused(
    trading_db: TradingDb, costs: dict[str, str], constraint: str
) -> None:
    async def attempt(connection: AsyncConnection) -> None:
        await _insert_fill(connection, **costs)

    error = _refused(trading_db.app_url, attempt)
    assert isinstance(error, IntegrityError)
    assert constraint in str(error)


def test_current_state_accepts_zero_cash(trading_db: TradingDb) -> None:
    async def work(connection: AsyncConnection) -> str:
        await _insert_state(connection, "0.00")
        value: str = await connection.scalar(text("SELECT cash::text FROM portfolio_state_current"))
        return value

    assert _rolled_back(trading_db.app_url, work) == "0.00"


def test_current_state_refuses_negative_cash(trading_db: TradingDb) -> None:
    async def attempt(connection: AsyncConnection) -> None:
        await _insert_state(connection, "-0.01")

    error = _refused(trading_db.app_url, attempt)
    assert isinstance(error, IntegrityError)
    assert "portfolio_state_current_cash_non_negative" in str(error)


# --- migration up/down/up -----------------------------------------------------------------


async def _schema_objects(url: str) -> tuple[set[str], set[str]]:
    async def work(connection: AsyncConnection) -> tuple[set[str], set[str]]:
        tables = await connection.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname = current_schema()")
        )
        functions = await connection.execute(
            text(
                "SELECT proname FROM pg_proc"
                " WHERE pronamespace = (SELECT oid FROM pg_namespace"
                " WHERE nspname = current_schema())"
            )
        )
        return {row[0] for row in tables}, {row[0] for row in functions}

    result: tuple[set[str], set[str]] = await _with_connection(url, work)
    return result


def test_the_migration_reverses_fully_and_applies_again() -> None:
    with _fresh_database() as database, _database_url(database.app_url):
        config = _alembic_config()
        command.upgrade(config, "head")
        tables, functions = run(_schema_objects(database.app_url))
        assert tables >= NEW_TABLES
        assert functions >= NEW_FUNCTIONS

        command.downgrade(config, "0001")
        tables, functions = run(_schema_objects(database.app_url))
        assert not tables & NEW_TABLES
        assert not functions & NEW_FUNCTIONS
        assert {"job", "outbox", "processed_events"} <= tables

        command.upgrade(config, "head")
        command.downgrade(config, "base")
        command.upgrade(config, "head")
        tables, functions = run(_schema_objects(database.app_url))
        assert tables >= NEW_TABLES
        assert functions >= NEW_FUNCTIONS
