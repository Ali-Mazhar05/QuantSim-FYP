"""The table definitions in ``qs_trading.models`` render to exactly the DDL the migrations
emit, checked without a database by running the migrations in Alembic's offline (SQL)
mode. The database tests then compare the two against a real schema as well."""

import io
import re
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Index, Numeric, Table
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from qs_template.messaging import messaging_metadata
from qs_trading import models
from qs_trading.domain.events import EventType

SERVICE_ROOT = Path(__file__).resolve().parents[2]
DIALECT = postgresql.dialect()  # type: ignore[no-untyped-call]

PRICE_COLUMNS = {
    "order": {"limit_price"},
    "fill": {"reference_price", "fill_price", "slippage"},
}
CASH_COLUMNS = {
    "portfolio": {"initial_capital"},
    "fill": {"cost_fixed", "cost_per_share", "cost_percentage", "cost_total", "cash_after"},
    "holding_history": {"cost_basis"},
    "portfolio_value": {
        "cash",
        "market_value",
        "value",
        "realised_pnl",
        "unrealised_pnl",
        "total_costs",
    },
    "portfolio_metrics": {"final_value", "total_costs"},
    "portfolio_state_current": {"cash"},
}


def _normalise(sql: str) -> str:
    return " ".join(sql.split()).rstrip(";").strip()


@pytest.fixture(scope="module")
def migration_sql() -> str:
    """Every migration up to head, rendered as SQL without connecting anywhere."""
    buffer = io.StringIO()
    config = Config(str(SERVICE_ROOT / "alembic.ini"), output_buffer=buffer)
    config.set_main_option("script_location", str(SERVICE_ROOT / "migrations"))
    with pytest.MonkeyPatch.context() as patch:
        # Offline mode only needs the dialect; nothing is contacted
        patch.setenv("DATABASE_URL", "postgresql+asyncpg://offline:offline@127.0.0.1:1/offline")
        command.upgrade(config, "head", sql=True)
    return buffer.getvalue()


def _created_tables(sql: str) -> dict[str, str]:
    blocks = re.findall(r"^(CREATE TABLE (\"?\w+\"?) \(.*?^\));", sql, re.MULTILINE | re.DOTALL)
    return {name.strip('"'): _normalise(block) for block, name in blocks}


def _created_indexes(sql: str) -> set[str]:
    return {_normalise(line) for line in re.findall(r"^CREATE INDEX .*?;", sql, re.MULTILINE)}


def _all_tables() -> list[Table]:
    return [*models.metadata.tables.values(), *messaging_metadata.tables.values()]


def test_the_migrations_create_exactly_the_model_tables(migration_sql: str) -> None:
    created = set(_created_tables(migration_sql)) - {"alembic_version"}
    assert created == {table.name for table in _all_tables()}


@pytest.mark.parametrize("table", _all_tables(), ids=lambda table: table.name)
def test_each_table_matches_its_migration_ddl(migration_sql: str, table: Table) -> None:
    expected = _normalise(str(CreateTable(table).compile(dialect=DIALECT)))
    assert _created_tables(migration_sql)[table.name] == expected


def test_the_migrations_create_exactly_the_model_indexes(migration_sql: str) -> None:
    indexes: list[Index] = [index for table in _all_tables() for index in table.indexes]
    expected = {_normalise(str(CreateIndex(index).compile(dialect=DIALECT))) for index in indexes}
    assert _created_indexes(migration_sql) == expected


def test_the_log_and_the_value_series_are_hypertables(migration_sql: str) -> None:
    hypertables = set(re.findall(r"create_hypertable\('(\w+)', by_range\('(\w+)'", migration_sql))
    assert hypertables == {("trade_event", "event_time"), ("portfolio_value", "ts")}


def test_the_log_is_guarded_and_revoked(migration_sql: str) -> None:
    sql = _normalise(migration_sql)
    assert (
        "CREATE TRIGGER trade_event_append_only BEFORE UPDATE OR DELETE ON trade_event"
        " FOR EACH ROW" in sql
    )
    assert "CREATE TRIGGER trade_event_seq_follows BEFORE INSERT ON trade_event" in sql
    assert "REVOKE UPDATE, DELETE, TRUNCATE ON trade_event FROM PUBLIC, CURRENT_USER" in sql


def test_the_event_type_check_lists_every_event_type(migration_sql: str) -> None:
    ddl = _created_tables(migration_sql)["trade_event"]
    found = re.search(r"CONSTRAINT trade_event_type_valid CHECK \(type IN \(([^)]*)\)\)", ddl)
    assert found is not None
    assert [value.strip().strip("'") for value in found.group(1).split(",")] == list(EventType)


@pytest.mark.parametrize(
    ("columns", "scale"), [(PRICE_COLUMNS, 8), (CASH_COLUMNS, 2)], ids=["prices", "cash"]
)
def test_money_columns_use_fixed_precision(columns: dict[str, set[str]], scale: int) -> None:
    for table_name, names in columns.items():
        table = models.metadata.tables[table_name]
        for name in names:
            column_type = table.c[name].type
            assert isinstance(column_type, Numeric), (table_name, name)
            assert (column_type.precision, column_type.scale) == (20, scale), (table_name, name)
            assert column_type.asdecimal, (table_name, name)
