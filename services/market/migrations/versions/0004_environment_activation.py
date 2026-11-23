"""The fingerprint frozen when an environment is activated for replay.

One row per environment; activating again re-freezes it. The environment's own status moves to
``active`` in the same transaction (and is audited there).

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "environment_activation",
        sa.Column("environment_id", sa.Uuid(), primary_key=True),
        sa.Column("source_fingerprint", sa.Text(), nullable=False),
        sa.Column("missing_session_count", sa.Integer(), nullable=False),
        sa.Column("activated_by", sa.Uuid(), nullable=False),
        sa.Column(
            "activated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["environment_id"], ["market_environment.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "source_fingerprint ~ '^xxh3:[0-9a-f]{32}$'",
            name="environment_activation_fingerprint_format",
        ),
        sa.CheckConstraint(
            "missing_session_count >= 0", name="environment_activation_missing_not_negative"
        ),
    )


def downgrade() -> None:
    op.drop_table("environment_activation")
