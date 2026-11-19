"""The server-side replay clock (B13).

One row per replay session over an activated environment: where the clock stood (the anchor),
when, at what speed and in which state. The position is computed on read, so nothing runs in the
background and a restart loses nothing. Every change is audited, as environments are.

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa
from alembic import op

from qs_template.audit import audit_table_statements

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "replay_session",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("environment_id", sa.Uuid(), nullable=False),
        sa.Column("anchor_index", sa.Integer(), nullable=False),
        sa.Column("anchor_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("speed", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("state", sa.Text(), nullable=False, server_default=sa.text("'paused'")),
        sa.Column("session_count", sa.Integer(), nullable=False),
        sa.Column("source_fingerprint", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["environment_id"], ["market_environment.id"], ondelete="CASCADE"),
        sa.CheckConstraint("speed IN (1, 5, 20)", name="replay_session_speed_valid"),
        sa.CheckConstraint("state IN ('playing', 'paused')", name="replay_session_state_valid"),
        sa.CheckConstraint("session_count >= 1", name="replay_session_has_sessions"),
        sa.CheckConstraint(
            "anchor_index >= 0 AND anchor_index < session_count",
            name="replay_session_anchor_in_range",
        ),
        sa.CheckConstraint(
            "source_fingerprint ~ '^xxh3:[0-9a-f]{32}$'", name="replay_session_fingerprint_format"
        ),
    )
    op.create_index(
        "replay_session_environment", "replay_session", ["environment_id", "created_at"]
    )
    for statement in audit_table_statements("replay_session"):
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS replay_session_audit ON replay_session")
    op.drop_table("replay_session")
