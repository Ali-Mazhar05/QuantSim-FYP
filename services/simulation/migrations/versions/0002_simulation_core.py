"""simulation_db core: calibrations, runs, statistics, paths and scenarios.

The invariant that matters most: run_instrument points at calibration (id, instrument_id), so a run
can never use another instrument's calibration, even through raw SQL (B-FR-12).

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

PRICE = sa.Numeric(23, 10)
STATISTIC = sa.Numeric(28, 12)
MODELS = "'gbm', 'ou', 'merton'"
MAX_PATHS = 100_000
MAX_STEPS = 2_520
FULL_STORAGE_MAX_VALUES = 252_000


def _number_param(key: str, condition: str) -> str:
    value = f"(params ->> '{key}')::numeric"
    return (
        f"CASE WHEN jsonb_typeof(params -> '{key}') = 'number' "
        f"THEN {condition.format(v=value)} ELSE false END"
    )


PRICE_SHOCK_BOUNDS = (
    "type <> 'price_shock' OR ("
    + _number_param("drop", "{v} > 0 AND {v} < 1")
    + " AND "
    + _number_param("at_step", "{v} >= 1 AND {v} = trunc({v})")
    + ")"
)
VOL_MULTIPLIER_BOUNDS = (
    "type <> 'vol_multiplier' OR ("
    + _number_param("multiplier", "{v} >= 1 AND {v} <= 10")
    + " AND "
    + _number_param("from_step", "{v} >= 1 AND {v} = trunc({v})")
    + " AND "
    + _number_param("to_step", "{v} >= 1 AND {v} = trunc({v})")
    + ")"
)


def _created_at() -> sa.Column[sa.DateTime]:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )


def upgrade() -> None:
    op.create_table(
        "instrument_ref",
        sa.Column("instrument_id", sa.Uuid(), primary_key=True),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("char_length(symbol) >= 1", name="instrument_ref_symbol"),
        sa.CheckConstraint("status IN ('active', 'retired')", name="instrument_ref_status"),
    )

    op.create_table(
        "scenario",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("params", postgresql.JSONB(), nullable=False),
        _created_at(),
        sa.UniqueConstraint("code", name="scenario_code"),
        sa.CheckConstraint("code ~ '^[a-z][a-z0-9_]{1,63}$'", name="scenario_code_format"),
        sa.CheckConstraint("char_length(name) BETWEEN 1 AND 120", name="scenario_name_length"),
        sa.CheckConstraint("type IN ('price_shock', 'vol_multiplier')", name="scenario_type"),
        sa.CheckConstraint("jsonb_typeof(params) = 'object'", name="scenario_params_object"),
        sa.CheckConstraint(PRICE_SHOCK_BOUNDS, name="scenario_price_shock_bounds"),
        sa.CheckConstraint(VOL_MULTIPLIER_BOUNDS, name="scenario_vol_multiplier_bounds"),
    )

    op.create_table(
        "calibration",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("instrument_id", sa.Uuid(), nullable=False),
        sa.Column("window_start", sa.Date(), nullable=False),
        sa.Column("window_end", sa.Date(), nullable=False),
        sa.Column("params", postgresql.JSONB(), nullable=False),
        sa.Column("std_errors", postgresql.JSONB(), nullable=False),
        sa.Column("log_likelihood", STATISTIC, nullable=False),
        sa.Column("aic", STATISTIC, nullable=False),
        sa.Column("n_obs", sa.Integer(), nullable=False),
        sa.Column("converged", sa.Boolean(), nullable=False),
        sa.Column("input_fingerprint", sa.Text(), nullable=False),
        sa.Column("qs_quant_version", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        _created_at(),
        sa.UniqueConstraint("id", "instrument_id", name="calibration_id_instrument"),
        sa.CheckConstraint(f"model IN ({MODELS})", name="calibration_model"),
        sa.CheckConstraint("window_start < window_end", name="calibration_window_valid"),
        sa.CheckConstraint("n_obs >= 60", name="calibration_enough_observations"),
        sa.CheckConstraint(
            "jsonb_typeof(params) = 'object' AND jsonb_typeof(std_errors) = 'object'",
            name="calibration_json_objects",
        ),
        sa.CheckConstraint("char_length(input_fingerprint) >= 1", name="calibration_fingerprint"),
    )
    op.create_index("calibration_by_instrument", "calibration", ["instrument_id", "created_at"])

    op.create_table(
        "run",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("n_paths", sa.Integer(), nullable=False),
        sa.Column("n_steps", sa.Integer(), nullable=False),
        sa.Column("seed", sa.BigInteger(), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="queued"),
        sa.Column("storage_mode", sa.Text(), nullable=False),
        sa.Column("parent_run_id", sa.Uuid()),
        sa.Column("scenario_id", sa.Uuid()),
        sa.Column("job_id", sa.Uuid()),
        sa.Column("median_path_index", sa.Integer()),
        sa.Column("error", sa.Text()),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        _created_at(),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["parent_run_id"], ["run.id"], name="run_parent"),
        sa.ForeignKeyConstraint(["scenario_id"], ["scenario.id"], name="run_scenario"),
        sa.ForeignKeyConstraint(["job_id"], ["job.id"], name="run_job"),
        sa.UniqueConstraint("idempotency_key", name="run_idempotency_key"),
        sa.CheckConstraint(f"model IN ({MODELS})", name="run_model"),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed')", name="run_status"
        ),
        sa.CheckConstraint("storage_mode IN ('full', 'quantiles')", name="run_storage_mode"),
        sa.CheckConstraint(f"n_paths BETWEEN 1 AND {MAX_PATHS}", name="run_paths_within_limits"),
        sa.CheckConstraint(f"n_steps BETWEEN 1 AND {MAX_STEPS}", name="run_steps_within_limits"),
        sa.CheckConstraint("seed >= 0", name="run_seed_not_negative"),
        sa.CheckConstraint(
            f"storage_mode <> 'full' OR n_paths * n_steps <= {FULL_STORAGE_MAX_VALUES}",
            name="run_full_storage_within_rule",
        ),
        sa.CheckConstraint(
            "(parent_run_id IS NULL) = (scenario_id IS NULL)", name="run_lineage_complete"
        ),
        sa.CheckConstraint(
            "parent_run_id IS NULL OR parent_run_id <> id", name="run_not_its_own_parent"
        ),
        sa.CheckConstraint(
            "median_path_index IS NULL OR (median_path_index >= 0 AND median_path_index < n_paths)",
            name="run_median_path_in_range",
        ),
        sa.CheckConstraint(
            "status <> 'completed' OR median_path_index IS NOT NULL",
            name="run_completed_has_median_path",
        ),
    )
    op.create_index("run_status_created", "run", ["status", "created_at"])
    op.create_index("run_parent", "run", ["parent_run_id"])

    op.create_table(
        "run_instrument",
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("instrument_id", sa.Uuid(), nullable=False),
        sa.Column("calibration_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("s0", PRICE, nullable=False),
        sa.PrimaryKeyConstraint("run_id", "instrument_id", name="run_instrument_pk"),
        sa.ForeignKeyConstraint(
            ["run_id"], ["run.id"], name="run_instrument_run", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["calibration_id", "instrument_id"],
            ["calibration.id", "calibration.instrument_id"],
            name="run_instrument_calibration_same_instrument",
        ),
        sa.UniqueConstraint("run_id", "position", name="run_instrument_position"),
        sa.CheckConstraint("position >= 0", name="run_instrument_position_not_negative"),
        sa.CheckConstraint("s0 > 0", name="run_instrument_start_price_positive"),
    )

    op.create_table(
        "run_correlation",
        sa.Column("run_id", sa.Uuid(), primary_key=True),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("matrix", postgresql.JSONB(), nullable=False),
        sa.Column("repair_applied", sa.Boolean(), nullable=False),
        sa.Column("min_eigenvalue_before", STATISTIC, nullable=False),
        sa.Column("frobenius_change", STATISTIC, nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"], ["run.id"], name="run_correlation_run", ondelete="CASCADE"
        ),
        sa.CheckConstraint("size >= 1", name="run_correlation_size"),
        sa.CheckConstraint(
            "jsonb_typeof(matrix) = 'array' AND jsonb_array_length(matrix) = size",
            name="run_correlation_matrix_size",
        ),
        sa.CheckConstraint("frobenius_change >= 0", name="run_correlation_change_not_negative"),
        sa.CheckConstraint(
            "repair_applied OR frobenius_change = 0", name="run_correlation_repair_recorded"
        ),
    )

    op.create_table(
        "run_statistics",
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("instrument_id", sa.Uuid(), nullable=False),
        sa.Column("mean_price", PRICE, nullable=False),
        sa.Column("median_price", PRICE, nullable=False),
        sa.Column("p5_price", PRICE, nullable=False),
        sa.Column("p95_price", PRICE, nullable=False),
        sa.Column("var95", STATISTIC, nullable=False),
        sa.Column("cvar95", STATISTIC, nullable=False),
        sa.PrimaryKeyConstraint("run_id", "instrument_id", name="run_statistics_pk"),
        sa.ForeignKeyConstraint(
            ["run_id", "instrument_id"],
            ["run_instrument.run_id", "run_instrument.instrument_id"],
            name="run_statistics_run_instrument",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("var95 <= cvar95", name="run_statistics_var_not_above_cvar"),
        sa.CheckConstraint(
            "p5_price <= median_price AND median_price <= p95_price",
            name="run_statistics_percentiles_ordered",
        ),
    )

    op.create_table(
        "path_value",
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("instrument_id", sa.Uuid(), nullable=False),
        sa.Column("path_index", sa.Integer(), nullable=False),
        sa.Column("step", sa.Integer(), nullable=False),
        sa.Column("price", PRICE, nullable=False),
        sa.PrimaryKeyConstraint(
            "run_id", "instrument_id", "path_index", "step", name="path_value_pk"
        ),
        sa.ForeignKeyConstraint(
            ["run_id", "instrument_id"],
            ["run_instrument.run_id", "run_instrument.instrument_id"],
            name="path_value_run_instrument",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("path_index >= 0 AND step >= 1", name="path_value_index_and_step"),
        sa.CheckConstraint("price > 0", name="path_value_price_positive"),
    )
    op.create_index(
        "path_value_by_step", "path_value", ["run_id", "instrument_id", "step", "path_index"]
    )

    op.create_table(
        "path_quantile",
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("instrument_id", sa.Uuid(), nullable=False),
        sa.Column("step", sa.Integer(), nullable=False),
        sa.Column("q01", PRICE, nullable=False),
        sa.Column("q05", PRICE, nullable=False),
        sa.Column("q25", PRICE, nullable=False),
        sa.Column("q50", PRICE, nullable=False),
        sa.Column("q75", PRICE, nullable=False),
        sa.Column("q95", PRICE, nullable=False),
        sa.Column("q99", PRICE, nullable=False),
        sa.PrimaryKeyConstraint("run_id", "instrument_id", "step", name="path_quantile_pk"),
        sa.ForeignKeyConstraint(
            ["run_id", "instrument_id"],
            ["run_instrument.run_id", "run_instrument.instrument_id"],
            name="path_quantile_run_instrument",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("step >= 1", name="path_quantile_step"),
        sa.CheckConstraint(
            "q01 > 0 AND q01 <= q05 AND q05 <= q25 AND q25 <= q50"
            " AND q50 <= q75 AND q75 <= q95 AND q95 <= q99",
            name="path_quantile_ordered",
        ),
    )


def downgrade() -> None:
    for table in (
        "path_quantile",
        "path_value",
        "run_statistics",
        "run_correlation",
        "run_instrument",
        "run",
        "calibration",
        "scenario",
        "instrument_ref",
    ):
        op.drop_table(table)
