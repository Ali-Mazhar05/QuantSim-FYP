"""Automatic audit trail inside each service's own database (FR-PLT-006..008,
NFR-AUD-001, NFR-AUD-002, NFR-INT-005, NFR-SEC-005).

A trigger on every audited table writes one ``audit_log`` row per inserted, updated or
deleted row, with the full before and after state, the acting user and the request id.
Because the trigger runs in the database, no code path can change audited data without
leaving a record. Deleted rows stay readable in the log, and the log itself refuses
UPDATE and DELETE, even from the table owner.

In a migration::

    for statement in AUDIT_SETUP_STATEMENTS:            # once per database
        op.execute(statement)
    for statement in audit_table_statements("instrument"):
        op.execute(statement)

At request time, :func:`set_audit_context` tells the trigger who is acting.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# One statement per item: asyncpg (and so Alembic on asyncpg) runs one statement per call
AUDIT_SETUP_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS audit_log (
        id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        table_name  text        NOT NULL,
        operation   text        NOT NULL CHECK (operation IN ('INSERT', 'UPDATE', 'DELETE')),
        row_id      text        NOT NULL,
        old_data    jsonb,
        new_data    jsonb,
        changed_by  text,
        request_id  text,
        changed_at  timestamptz NOT NULL DEFAULT clock_timestamp(),
        txid        bigint      NOT NULL DEFAULT txid_current()
    )
    """,
    "CREATE INDEX IF NOT EXISTS audit_log_record ON audit_log (table_name, row_id, id)",
    """
    CREATE OR REPLACE FUNCTION qs_audit_row() RETURNS trigger
    LANGUAGE plpgsql AS $$
    DECLARE
        id_column text := TG_ARGV[0];
        old_row   jsonb := CASE WHEN TG_OP IN ('UPDATE', 'DELETE') THEN to_jsonb(OLD) END;
        new_row   jsonb := CASE WHEN TG_OP IN ('INSERT', 'UPDATE') THEN to_jsonb(NEW) END;
    BEGIN
        INSERT INTO audit_log (table_name, operation, row_id, old_data, new_data,
                               changed_by, request_id)
        VALUES (TG_TABLE_NAME, TG_OP, COALESCE(new_row, old_row) ->> id_column,
                old_row, new_row,
                NULLIF(current_setting('qs.user_id', true), ''),
                NULLIF(current_setting('qs.request_id', true), ''));
        RETURN NULL;
    END;
    $$
    """,
    """
    CREATE OR REPLACE FUNCTION qs_audit_log_is_append_only() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        RAISE EXCEPTION 'audit_log is append-only: % is not allowed', TG_OP
            USING ERRCODE = 'insufficient_privilege';
    END;
    $$
    """,
    "DROP TRIGGER IF EXISTS audit_log_append_only ON audit_log",
    """
    CREATE TRIGGER audit_log_append_only
        BEFORE UPDATE OR DELETE OR TRUNCATE ON audit_log
        FOR EACH STATEMENT EXECUTE FUNCTION qs_audit_log_is_append_only()
    """,
)


def audit_table_statements(table: str, id_column: str = "id") -> tuple[str, ...]:
    """Statements that start auditing ``table``; ``id_column`` identifies each row."""
    for name in (table, id_column):
        if not name.replace("_", "").isalnum():
            raise ValueError(f"not a plain SQL identifier: {name!r}")
    return (
        f"DROP TRIGGER IF EXISTS {table}_audit ON {table}",
        f"CREATE TRIGGER {table}_audit AFTER INSERT OR UPDATE OR DELETE ON {table}"
        f" FOR EACH ROW EXECUTE FUNCTION qs_audit_row('{id_column}')",
    )


async def set_audit_context(
    session: AsyncSession, *, user_id: uuid.UUID | str | None, request_id: str | None
) -> None:
    """Record who is acting for the rest of the session's current transaction."""
    await session.execute(
        text(
            "SELECT set_config('qs.user_id', :user_id, true),"
            " set_config('qs.request_id', :request_id, true)"
        ),
        {"user_id": str(user_id) if user_id else "", "request_id": request_id or ""},
    )


@dataclass(frozen=True)
class AuditEntry:
    operation: str
    old_data: dict[str, Any] | None
    new_data: dict[str, Any] | None
    changed_by: str | None
    request_id: str | None
    changed_at: datetime


async def record_history(session: AsyncSession, table: str, row_id: str) -> list[AuditEntry]:
    """Every recorded change to one row, oldest first, including its deletion."""
    rows = await session.execute(
        text(
            "SELECT operation, old_data, new_data, changed_by, request_id, changed_at"
            " FROM audit_log WHERE table_name = :table AND row_id = :row_id ORDER BY id"
        ),
        {"table": table, "row_id": row_id},
    )
    return [AuditEntry(*row) for row in rows.all()]
