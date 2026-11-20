"""trading_db: a strategy's kind must be one of the built-in strategies.

0002 only checked the kind's format; the API already refuses an unknown kind, and this
makes the database refuse it too. The list is a frozen copy of
``qs_trading.domain.strategies.KINDS`` at this revision; a test checks that the model's
CHECK and this one still name the same kinds. A new built-in kind needs a new migration.
The downgrade restores the format CHECK of 0002.

Revision ID: 0003
Revises: 0002
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

# Frozen copy of qs_trading.domain.strategies.KINDS at this revision
STRATEGY_KINDS = ("buy_and_hold", "ma_crossover", "momentum", "mean_reversion")

KIND_FORMAT = "kind ~ '^[a-z][a-z0-9_]{0,39}$'"


def kind_check() -> str:
    return "kind IN (" + ", ".join(f"'{kind}'" for kind in STRATEGY_KINDS) + ")"


def upgrade() -> None:
    op.drop_constraint("strategy_kind_format", "strategy", type_="check")
    op.create_check_constraint("strategy_kind_known", "strategy", kind_check())


def downgrade() -> None:
    op.drop_constraint("strategy_kind_known", "strategy", type_="check")
    op.create_check_constraint("strategy_kind_format", "strategy", KIND_FORMAT)
