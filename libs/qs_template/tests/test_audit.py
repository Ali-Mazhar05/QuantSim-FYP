import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from qs_template import Database
from qs_template.audit import (
    AUDIT_SETUP_STATEMENTS,
    audit_table_statements,
    record_history,
    set_audit_context,
)

ADMIN = uuid.UUID("0b7f6a52-1d4e-4c3a-8f0e-2a9b6c5d4e3f")


@pytest.fixture
async def db(database: Database) -> Database:
    async with database.engine.begin() as connection:
        await connection.execute(
            text("CREATE TABLE instrument (id int PRIMARY KEY, symbol text, status text)")
        )
        for statement in (*AUDIT_SETUP_STATEMENTS, *audit_table_statements("instrument")):
            await connection.exec_driver_sql(statement)
    return database


@pytest.mark.db
async def test_records_every_change_with_before_and_after_state(db: Database) -> None:
    async with db.transaction() as session:
        await set_audit_context(session, user_id=ADMIN, request_id="req-1")
        await session.execute(text("INSERT INTO instrument VALUES (1, 'AAPL', 'active')"))
    async with db.transaction() as session:
        await set_audit_context(session, user_id=ADMIN, request_id="req-2")
        await session.execute(text("UPDATE instrument SET status = 'retired' WHERE id = 1"))

    async with db.transaction() as session:
        history = await record_history(session, "instrument", "1")

    assert [h.operation for h in history] == ["INSERT", "UPDATE"]
    assert history[0].old_data is None
    assert history[0].new_data == {"id": 1, "symbol": "AAPL", "status": "active"}
    assert history[1].old_data == {"id": 1, "symbol": "AAPL", "status": "active"}
    assert history[1].new_data == {"id": 1, "symbol": "AAPL", "status": "retired"}
    assert [h.changed_by for h in history] == [str(ADMIN), str(ADMIN)]
    assert [h.request_id for h in history] == ["req-1", "req-2"]


@pytest.mark.db
async def test_deleted_rows_remain_queryable(db: Database) -> None:
    async with db.transaction() as session:
        await session.execute(text("INSERT INTO instrument VALUES (7, 'MSFT', 'active')"))
        await session.execute(text("DELETE FROM instrument WHERE id = 7"))

    async with db.transaction() as session:
        history = await record_history(session, "instrument", "7")

    assert history[-1].operation == "DELETE"
    assert history[-1].old_data == {"id": 7, "symbol": "MSFT", "status": "active"}
    assert history[-1].new_data is None


@pytest.mark.db
async def test_changes_without_context_are_still_recorded(db: Database) -> None:
    async with db.transaction() as session:
        await session.execute(text("INSERT INTO instrument VALUES (3, 'NVDA', 'active')"))

    async with db.transaction() as session:
        history = await record_history(session, "instrument", "3")

    assert len(history) == 1
    assert history[0].changed_by is None


@pytest.mark.db
async def test_context_does_not_leak_into_the_next_transaction(db: Database) -> None:
    async with db.transaction() as session:
        await set_audit_context(session, user_id=ADMIN, request_id="req-1")
        await session.execute(text("INSERT INTO instrument VALUES (4, 'AMD', 'active')"))
    async with db.transaction() as session:
        await session.execute(text("UPDATE instrument SET status = 'x' WHERE id = 4"))

    async with db.transaction() as session:
        history = await record_history(session, "instrument", "4")

    assert [h.changed_by for h in history] == [str(ADMIN), None]


@pytest.mark.db
@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE audit_log SET changed_by = 'someone-else'",
        "DELETE FROM audit_log",
        "TRUNCATE audit_log",
    ],
)
async def test_audit_log_is_append_only(db: Database, statement: str) -> None:
    async with db.transaction() as session:
        await session.execute(text("INSERT INTO instrument VALUES (5, 'TSLA', 'active')"))

    with pytest.raises(DBAPIError, match="append-only"):
        async with db.transaction() as session:
            await session.execute(text(statement))

    async with db.transaction() as session:
        assert len(await record_history(session, "instrument", "5")) == 1


def test_refuses_table_names_that_are_not_plain_identifiers() -> None:
    with pytest.raises(ValueError, match="identifier"):
        audit_table_statements("instrument; DROP TABLE audit_log")
