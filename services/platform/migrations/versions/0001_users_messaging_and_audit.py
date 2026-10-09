"""Users, event outbox, processed events and the audit trail.

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from qs_template.audit import AUDIT_SETUP_STATEMENTS, audit_table_statements

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

ROLES = "'admin', 'quant', 'analyst', 'viewer'"


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("username", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("failed_logins", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("locked_until", sa.DateTime(timezone=True)),
        sa.Column("last_login_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("deactivated_at", sa.DateTime(timezone=True)),
        sa.Column("created_by", sa.Uuid()),
        sa.CheckConstraint(f"role IN ({ROLES})", name="users_role_valid"),
        sa.CheckConstraint("username ~ '^[a-z0-9._-]{3,40}$'", name="users_username_format"),
        sa.CheckConstraint("failed_logins >= 0", name="users_failed_logins_non_negative"),
        sa.CheckConstraint(
            "(is_active AND deactivated_at IS NULL)"
            " OR (NOT is_active AND deactivated_at IS NOT NULL)",
            name="users_deactivation_consistent",
        ),
    )
    op.create_index(
        "users_username_unique", "users", [sa.text("lower(username)")], unique=True
    )
    op.create_index("users_email_unique", "users", [sa.text("lower(email)")], unique=True)

    op.create_table(
        "outbox",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("event_id", sa.Uuid(), nullable=False, unique=True),
        sa.Column("topic", sa.Text(), nullable=False),
        sa.Column("message_key", sa.Text(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("last_error", sa.Text()),
    )
    op.create_index(
        "outbox_pending", "outbox", ["id"], postgresql_where=sa.text("published_at IS NULL")
    )

    op.create_table(
        "processed_events",
        sa.Column("consumer_group", sa.Text(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column(
            "processed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("consumer_group", "event_id"),
    )

    for statement in AUDIT_SETUP_STATEMENTS:
        op.execute(statement)
    # Password hashes never reach the audit log
    for statement in audit_table_statements("users", exclude=("password_hash",)):
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS users_audit ON users")
    op.drop_table("processed_events")
    op.drop_table("outbox")
    op.drop_table("users")
    op.execute("DROP TRIGGER IF EXISTS audit_log_append_only ON audit_log")
    op.execute("DROP TABLE IF EXISTS audit_log")
    op.execute("DROP FUNCTION IF EXISTS qs_audit_log_is_append_only()")
    op.execute("DROP FUNCTION IF EXISTS qs_audit_row()")
