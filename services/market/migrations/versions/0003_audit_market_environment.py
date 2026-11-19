"""Audit every change to a market environment, as instruments already are.

Environments are created by users through the API from Iteration 1 on, so who created or
changed one must be on record (FR-PLT-006..008) and appear in the audit feed.

Revision ID: 0003
Revises: 0002
"""

from alembic import op

from qs_template.audit import audit_table_statements

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for statement in audit_table_statements("market_environment"):
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS market_environment_audit ON market_environment")
