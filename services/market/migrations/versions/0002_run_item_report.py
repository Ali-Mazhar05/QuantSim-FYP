"""Keep the gate's full report on each ingestion run item.

The item counters cannot hold per rule counts or flags, and a run that resumes after a
crash must still be able to report the instruments it did not repeat.

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ingestion_run_item", sa.Column("report", postgresql.JSONB()))


def downgrade() -> None:
    op.drop_column("ingestion_run_item", "report")
