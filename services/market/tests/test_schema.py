"""The schema built by the migrations: it matches the models exactly (migration protocol
rule 8), it is partitioned where it should be, and the database itself refuses data that
must never exist (NFR-INT-001, NFR-INT-003, FR-26, FR-PLT-006, NFR-INT-005)."""

import uuid
from collections.abc import Callable
from typing import Any

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import MetaData, Numeric, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from qs_market import models
from qs_template.messaging import messaging_metadata

from .conftest import run

PRICE_COLUMNS = {
    "open",
    "high",
    "low",
    "close",
    "dividend",
    "adj_open",
    "adj_high",
    "adj_low",
    "adj_close",
    "adj_volume",
    "volume",
}


def test_prices_and_volumes_use_fixed_precision_with_8_decimals() -> None:
    for table in (models.bar, models.corporate_action):
        for column in table.columns:
            if column.name in PRICE_COLUMNS:
                assert isinstance(column.type, Numeric), column
                assert column.type.scale == 8, column
                assert column.type.asdecimal, column


def _combined_metadata() -> MetaData:
    combined = MetaData()
    for source in (models.metadata, messaging_metadata):
        for table in source.tables.values():
            table.to_metadata(combined)
    return combined


def _diff(connection: Connection) -> list[Any]:
    def include(obj: Any, name: str | None, type_: str, reflected: bool, compare_to: Any) -> bool:
        # The audit trail is created from template SQL, not from SQLAlchemy models
        return not (type_ == "table" and name == "audit_log") and not (
            type_ == "index" and name == "audit_log_record"
        )

    context = MigrationContext.configure(
        connection, opts={"include_object": include, "compare_type": True}
    )
    return list(compare_metadata(context, _combined_metadata()))


async def _with_connection(url: str, work: Callable[[AsyncConnection], Any]) -> Any:
    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection:
            return await work(connection)
    finally:
        await engine.dispose()


@pytest.mark.db
def test_models_match_the_migrations_exactly(migrated_database_url: str) -> None:
    async def work(connection: AsyncConnection) -> list[Any]:
        return await connection.run_sync(_diff)

    assert run(_with_connection(migrated_database_url, work)) == []


@pytest.mark.db
def test_bars_and_returns_are_hypertables(migrated_database_url: str) -> None:
    async def work(connection: AsyncConnection) -> set[str]:
        rows = await connection.execute(
            text("SELECT hypertable_name FROM timescaledb_information.hypertables")
        )
        return {row[0] for row in rows}

    assert run(_with_connection(migrated_database_url, work)) == {"bar", "return_series"}


# --- rules the database enforces by itself -------------------------------------------

RUN_ID = uuid.uuid4()


async def _insert_instrument(connection: AsyncConnection, **overrides: Any) -> uuid.UUID:
    values: dict[str, Any] = {
        "id": uuid.uuid4(),
        "symbol": "AAPL",
        "name": "Apple Inc.",
        "exchange": "XNAS",
        "calendar": "XNYS",
        "currency": "USD",
        "asset_class": "equity",
        "vendor_symbol": "aapl",
    }
    values.update(overrides)
    await connection.execute(
        text(
            "INSERT INTO instrument (id, symbol, name, exchange, calendar, currency,"
            " asset_class, vendor_symbol)"
            " VALUES (:id, :symbol, :name, :exchange, :calendar, :currency, :asset_class,"
            " :vendor_symbol)"
        ),
        values,
    )
    instrument_id: uuid.UUID = values["id"]
    return instrument_id


async def _insert_bar(connection: AsyncConnection, instrument_id: uuid.UUID, **prices: Any) -> None:
    values: dict[str, Any] = {
        "instrument_id": instrument_id,
        "open": "10.00000000",
        "high": "11.00000000",
        "low": "9.00000000",
        "close": "10.50000000",
        "volume": "1000",
        "run_id": RUN_ID,
    }
    values.update(prices)
    await connection.execute(
        text(
            "INSERT INTO bar (instrument_id, session_date, ts, open, high, low, close, volume,"
            " content_hash, run_id, vendor, ruleset_version)"
            " VALUES (:instrument_id, DATE '2026-10-09', TIMESTAMPTZ '2026-10-09 20:00+00',"
            " :open, :high, :low, :close, :volume, 'h', :run_id, 'tiingo', '2026.10.1')"
        ),
        values,
    )


def _refused(url: str, attempt: Callable[[AsyncConnection], Any]) -> BaseException:
    """Run ``attempt`` in a transaction that is always rolled back; return its error."""

    async def work(connection: AsyncConnection) -> BaseException:
        transaction = await connection.begin()
        try:
            await attempt(connection)
        except DBAPIError as error:
            return error
        finally:
            await transaction.rollback()
        raise AssertionError("the database accepted data it must refuse")

    error: BaseException = run(_with_connection(url, work))
    return error


@pytest.mark.db
def test_a_valid_bar_is_accepted_with_8_decimal_prices(migrated_database_url: str) -> None:
    async def work(connection: AsyncConnection) -> str:
        transaction = await connection.begin()
        try:
            instrument_id = await _insert_instrument(connection)
            await _insert_bar(connection, instrument_id, close="10.12345678")
            value = await connection.scalar(text("SELECT close::text FROM bar"))
            return str(value)
        finally:
            await transaction.rollback()

    assert run(_with_connection(migrated_database_url, work)) == "10.12345678"


@pytest.mark.db
@pytest.mark.parametrize(
    ("prices", "constraint"),
    [
        ({"low": "12.00000000"}, "bar_low_not_above_high"),
        ({"low": "0"}, "bar_prices_positive"),
        ({"low": "-1"}, "bar_prices_positive"),
        ({"close": "11.50000000"}, "bar_open_close_in_range"),
        ({"volume": "-5"}, "bar_volume_non_negative"),
    ],
)
def test_impossible_bars_are_refused(
    migrated_database_url: str, prices: dict[str, str], constraint: str
) -> None:
    async def attempt(connection: AsyncConnection) -> None:
        instrument_id = await _insert_instrument(connection)
        await _insert_bar(connection, instrument_id, **prices)

    error = _refused(migrated_database_url, attempt)
    assert isinstance(error, IntegrityError)
    assert constraint in str(error)


@pytest.mark.db
def test_an_inverted_replay_window_is_refused(migrated_database_url: str) -> None:
    async def attempt(connection: AsyncConnection) -> None:
        await connection.execute(
            text(
                "INSERT INTO replay_session (name, instrument_ids, start_time, end_time,"
                " created_by) VALUES ('crash', '[]', TIMESTAMPTZ '2020-03-20 00:00+00',"
                " TIMESTAMPTZ '2020-03-01 00:00+00', gen_random_uuid())"
            )
        )

    error = _refused(migrated_database_url, attempt)
    assert "replay_session_window_valid" in str(error)


@pytest.mark.db
def test_a_run_report_that_does_not_add_up_is_refused(migrated_database_url: str) -> None:
    async def attempt(connection: AsyncConnection) -> None:
        instrument_id = await _insert_instrument(connection)
        run_id = await connection.scalar(
            text(
                "INSERT INTO ingestion_run (mode, vendor, requested_by)"
                " VALUES ('manual', 'tiingo', 'tests') RETURNING id"
            )
        )
        await connection.execute(
            text(
                "INSERT INTO ingestion_run_item (run_id, instrument_id, status, received,"
                " passed_untouched, rejected) VALUES (:run, :instrument, 'succeeded', 10, 7, 2)"
            ),
            {"run": run_id, "instrument": instrument_id},
        )

    error = _refused(migrated_database_url, attempt)
    assert "ingestion_run_item_reconciles" in str(error)


@pytest.mark.db
@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        ({"asset_class": "crypto"}, "instrument_asset_class_valid"),
        ({"symbol": "aapl"}, "instrument_symbol_format"),
        ({"exchange": "NASDAQ"}, "instrument_exchange_format"),
    ],
)
def test_invalid_instruments_are_refused(
    migrated_database_url: str, overrides: dict[str, str], constraint: str
) -> None:
    async def attempt(connection: AsyncConnection) -> None:
        await _insert_instrument(connection, **overrides)

    error = _refused(migrated_database_url, attempt)
    assert constraint in str(error)


@pytest.mark.db
def test_a_retired_instrument_needs_a_retirement_time(migrated_database_url: str) -> None:
    async def attempt(connection: AsyncConnection) -> None:
        instrument_id = await _insert_instrument(connection)
        await connection.execute(
            text("UPDATE instrument SET status = 'retired' WHERE id = :id"), {"id": instrument_id}
        )

    error = _refused(migrated_database_url, attempt)
    assert "instrument_retirement_consistent" in str(error)


@pytest.mark.db
def test_instrument_changes_are_audited_and_the_log_is_append_only(
    migrated_database_url: str,
) -> None:
    async def audited(connection: AsyncConnection) -> list[str]:
        transaction = await connection.begin()
        try:
            instrument_id = await _insert_instrument(connection)
            await connection.execute(
                text("UPDATE instrument SET notes = 'large cap' WHERE id = :id"),
                {"id": instrument_id},
            )
            rows = await connection.execute(
                text(
                    "SELECT operation FROM audit_log WHERE table_name = 'instrument'"
                    " AND row_id = :id ORDER BY id"
                ),
                {"id": str(instrument_id)},
            )
            return [row[0] for row in rows]
        finally:
            await transaction.rollback()

    assert run(_with_connection(migrated_database_url, audited)) == ["INSERT", "UPDATE"]

    async def tamper(connection: AsyncConnection) -> None:
        await _insert_instrument(connection)
        await connection.execute(text("DELETE FROM audit_log"))

    error = _refused(migrated_database_url, tamper)
    assert "append-only" in str(error)
