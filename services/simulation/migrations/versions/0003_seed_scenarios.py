"""The two stress scenarios a demo uses, as rows of data (B17).

Scenarios are data: these are examples a user can copy, change or delete; a new one needs no code.
A flash crash of 20% at step 21 (about a month into a run, permanent), and a volatility spike to
times the calibrated level over the next 43 steps (steps 21 to 63).

Revision ID: 0003
Revises: 0002
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

SEEDED = ("flash_crash", "vol_spike")


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO scenario (code, name, type, params) VALUES
          ('flash_crash', 'Flash crash: 20% in one step', 'price_shock',
           '{"drop": 0.2, "at_step": 21, "recovery_steps": 0}'::jsonb),
          ('vol_spike', 'Volatility spike: three times normal for two months', 'vol_multiplier',
           '{"multiplier": 3, "from_step": 21, "to_step": 63}'::jsonb)
        ON CONFLICT (code) DO NOTHING
        """
    )


def downgrade() -> None:
    # a seeded scenario that a run was stressed with is kept: the run points at it
    op.execute(
        "DELETE FROM scenario WHERE code IN ('flash_crash', 'vol_spike')"
        " AND NOT EXISTS (SELECT 1 FROM run WHERE run.scenario_id = scenario.id)"
    )
