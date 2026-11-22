"""Tables of simulation_db. Every change here needs a migration in ``migrations/versions``.

The database refuses what must never exist (NFR-INT-003, B-FR-12): a run instrument that points at
another instrument's calibration, an inverted calibration window, a derived run without its
scenario, full path storage beyond the ADR 03 limit, and scenario parameters out of bounds.
Prices and statistics are NUMERIC; the service converts floats to Decimal at its boundary.
"""

from collections.abc import Iterable
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    Numeric,
    PrimaryKeyConstraint,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

from qs_template.jobs import job_table

metadata = MetaData()

job = job_table(metadata)

PRICE = Numeric(23, 10)  # the precision of adjusted prices in market_db
STATISTIC = Numeric(28, 12)

MODELS = ("gbm", "ou", "merton")
RUN_STATUSES = ("queued", "running", "completed", "failed")
STORAGE_MODES = ("full", "quantiles")
SCENARIO_TYPES = ("price_shock", "vol_multiplier")

# Sizes a run may have, and the ADR 03 rule for keeping every path value
MAX_PATHS = 100_000
MAX_STEPS = 2_520
FULL_STORAGE_MAX_VALUES = 252_000  # paths x steps per instrument


def _one_of(column: str, values: Iterable[str]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _number_param(key: str, condition: str) -> str:
    """Parameter ``key`` is a JSON number and satisfies ``condition`` ({v} stands for its value)."""
    value = f"(params ->> '{key}')::numeric"
    return (
        f"CASE WHEN jsonb_typeof(params -> '{key}') = 'number' "
        f"THEN {condition.format(v=value)} ELSE false END"
    )


# One bound per parameter: a parameter that is missing, not a number or out of range refuses the row
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


def _created_at() -> Column[datetime]:
    return Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now())


# A local copy of what the simulation service shows about an instrument, kept from the
# instrument events. It is a cache for display; a calibration is validated against the market
# service when it is made, so no foreign key points here.
instrument_ref = Table(
    "instrument_ref",
    metadata,
    Column("instrument_id", Uuid, primary_key=True),
    Column("symbol", Text, nullable=False),
    Column("name", Text, nullable=False, server_default=""),
    Column("status", Text, nullable=False, server_default="active"),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint("char_length(symbol) >= 1", name="instrument_ref_symbol"),
    CheckConstraint(_one_of("status", ("active", "retired")), name="instrument_ref_status"),
)

# Stress overlays are data: a harsher flash crash is an INSERT (B-FR-16)
scenario = Table(
    "scenario",
    metadata,
    Column("id", Uuid, primary_key=True, server_default=text("gen_random_uuid()")),
    Column("code", Text, nullable=False),
    Column("name", Text, nullable=False),
    Column("type", Text, nullable=False),
    Column("params", JSONB, nullable=False),
    _created_at(),
    UniqueConstraint("code", name="scenario_code"),
    CheckConstraint("code ~ '^[a-z][a-z0-9_]{1,63}$'", name="scenario_code_format"),
    CheckConstraint("char_length(name) BETWEEN 1 AND 120", name="scenario_name_length"),
    CheckConstraint(_one_of("type", SCENARIO_TYPES), name="scenario_type"),
    CheckConstraint("jsonb_typeof(params) = 'object'", name="scenario_params_object"),
    CheckConstraint(PRICE_SHOCK_BOUNDS, name="scenario_price_shock_bounds"),
    CheckConstraint(VOL_MULTIPLIER_BOUNDS, name="scenario_vol_multiplier_bounds"),
)

# UNIQUE (id, instrument_id) is what lets run_instrument point at the pair, so a run cannot
# use another instrument's calibration even through raw SQL
calibration = Table(
    "calibration",
    metadata,
    Column("id", Uuid, primary_key=True, server_default=text("gen_random_uuid()")),
    Column("model", Text, nullable=False),
    Column("instrument_id", Uuid, nullable=False),
    Column("window_start", Date, nullable=False),
    Column("window_end", Date, nullable=False),
    Column("params", JSONB, nullable=False),
    Column("std_errors", JSONB, nullable=False),
    Column("log_likelihood", STATISTIC, nullable=False),
    Column("aic", STATISTIC, nullable=False),
    Column("n_obs", Integer, nullable=False),
    Column("converged", Boolean, nullable=False),
    Column("input_fingerprint", Text, nullable=False),
    Column("qs_quant_version", Text, nullable=False),
    Column("created_by", Uuid, nullable=False),
    _created_at(),
    UniqueConstraint("id", "instrument_id", name="calibration_id_instrument"),
    CheckConstraint(_one_of("model", MODELS), name="calibration_model"),
    CheckConstraint("window_start < window_end", name="calibration_window_valid"),
    CheckConstraint("n_obs >= 60", name="calibration_enough_observations"),
    CheckConstraint(
        "jsonb_typeof(params) = 'object' AND jsonb_typeof(std_errors) = 'object'",
        name="calibration_json_objects",
    ),
    CheckConstraint("char_length(input_fingerprint) >= 1", name="calibration_fingerprint"),
    Index("calibration_by_instrument", "instrument_id", "created_at"),
)

run = Table(
    "run",
    metadata,
    Column("id", Uuid, primary_key=True, server_default=text("gen_random_uuid()")),
    Column("model", Text, nullable=False),
    Column("n_paths", Integer, nullable=False),
    Column("n_steps", Integer, nullable=False),
    Column("seed", BigInteger, nullable=False),
    Column("idempotency_key", Text, nullable=False),
    Column("status", Text, nullable=False, server_default="queued"),
    Column("storage_mode", Text, nullable=False),
    Column("parent_run_id", Uuid),
    Column("scenario_id", Uuid),
    Column("job_id", Uuid),
    Column("median_path_index", Integer),
    Column("error", Text),
    Column("created_by", Uuid, nullable=False),
    _created_at(),
    Column("started_at", DateTime(timezone=True)),
    Column("finished_at", DateTime(timezone=True)),
    ForeignKeyConstraint(["parent_run_id"], ["run.id"], name="run_parent"),
    ForeignKeyConstraint(["scenario_id"], ["scenario.id"], name="run_scenario"),
    ForeignKeyConstraint(["job_id"], ["job.id"], name="run_job"),
    UniqueConstraint("idempotency_key", name="run_idempotency_key"),
    CheckConstraint(_one_of("model", MODELS), name="run_model"),
    CheckConstraint(_one_of("status", RUN_STATUSES), name="run_status"),
    CheckConstraint(_one_of("storage_mode", STORAGE_MODES), name="run_storage_mode"),
    CheckConstraint(f"n_paths BETWEEN 1 AND {MAX_PATHS}", name="run_paths_within_limits"),
    CheckConstraint(f"n_steps BETWEEN 1 AND {MAX_STEPS}", name="run_steps_within_limits"),
    CheckConstraint("seed >= 0", name="run_seed_not_negative"),
    CheckConstraint(
        f"storage_mode <> 'full' OR n_paths * n_steps <= {FULL_STORAGE_MAX_VALUES}",
        name="run_full_storage_within_rule",
    ),
    # a derived (stressed) run has both its parent and its scenario; a base run has neither
    CheckConstraint("(parent_run_id IS NULL) = (scenario_id IS NULL)", name="run_lineage_complete"),
    CheckConstraint("parent_run_id IS NULL OR parent_run_id <> id", name="run_not_its_own_parent"),
    CheckConstraint(
        "median_path_index IS NULL OR (median_path_index >= 0 AND median_path_index < n_paths)",
        name="run_median_path_in_range",
    ),
    # Lane A binds a portfolio to the median path of a completed run, so completion needs it
    CheckConstraint(
        "status <> 'completed' OR median_path_index IS NOT NULL",
        name="run_completed_has_median_path",
    ),
    Index("run_status_created", "status", "created_at"),
    Index("run_parent", "parent_run_id"),
)

run_instrument = Table(
    "run_instrument",
    metadata,
    Column("run_id", Uuid, nullable=False),
    Column("instrument_id", Uuid, nullable=False),
    Column("calibration_id", Uuid, nullable=False),
    Column("position", Integer, nullable=False),  # the instrument's place in the correlation matrix
    Column("s0", PRICE, nullable=False),
    PrimaryKeyConstraint("run_id", "instrument_id", name="run_instrument_pk"),
    ForeignKeyConstraint(["run_id"], ["run.id"], name="run_instrument_run", ondelete="CASCADE"),
    ForeignKeyConstraint(
        ["calibration_id", "instrument_id"],
        ["calibration.id", "calibration.instrument_id"],
        name="run_instrument_calibration_same_instrument",
    ),
    UniqueConstraint("run_id", "position", name="run_instrument_position"),
    CheckConstraint("position >= 0", name="run_instrument_position_not_negative"),
    CheckConstraint("s0 > 0", name="run_instrument_start_price_positive"),
)

run_correlation = Table(
    "run_correlation",
    metadata,
    Column("run_id", Uuid, primary_key=True),
    Column("size", Integer, nullable=False),
    # the matrix the generator was given, before repair: the repair is deterministic, so this plus
    # the record below reproduces the paths exactly (B-FR-14)
    Column("matrix", JSONB, nullable=False),
    Column("repair_applied", Boolean, nullable=False),
    Column("min_eigenvalue_before", STATISTIC, nullable=False),
    Column("frobenius_change", STATISTIC, nullable=False),
    ForeignKeyConstraint(["run_id"], ["run.id"], name="run_correlation_run", ondelete="CASCADE"),
    CheckConstraint("size >= 1", name="run_correlation_size"),
    CheckConstraint(
        "jsonb_typeof(matrix) = 'array' AND jsonb_array_length(matrix) = size",
        name="run_correlation_matrix_size",
    ),
    CheckConstraint("frobenius_change >= 0", name="run_correlation_change_not_negative"),
    CheckConstraint(
        "repair_applied OR frobenius_change = 0", name="run_correlation_repair_recorded"
    ),
)

run_statistics = Table(
    "run_statistics",
    metadata,
    Column("run_id", Uuid, nullable=False),
    Column("instrument_id", Uuid, nullable=False),
    Column("mean_price", PRICE, nullable=False),
    Column("median_price", PRICE, nullable=False),
    Column("p5_price", PRICE, nullable=False),
    Column("p95_price", PRICE, nullable=False),
    Column("var95", STATISTIC, nullable=False),
    Column("cvar95", STATISTIC, nullable=False),
    PrimaryKeyConstraint("run_id", "instrument_id", name="run_statistics_pk"),
    ForeignKeyConstraint(
        ["run_id", "instrument_id"],
        ["run_instrument.run_id", "run_instrument.instrument_id"],
        name="run_statistics_run_instrument",
        ondelete="CASCADE",
    ),
    CheckConstraint("var95 <= cvar95", name="run_statistics_var_not_above_cvar"),
    CheckConstraint(
        "p5_price <= median_price AND median_price <= p95_price",
        name="run_statistics_percentiles_ordered",
    ),
)

# Written with COPY for runs kept in full (ADR 03). A plain table: no time column helps the two
# access patterns, all steps of one path and one step across paths, which the key and index serve.
path_value = Table(
    "path_value",
    metadata,
    Column("run_id", Uuid, nullable=False),
    Column("instrument_id", Uuid, nullable=False),
    Column("path_index", Integer, nullable=False),
    Column("step", Integer, nullable=False),
    Column("price", PRICE, nullable=False),
    PrimaryKeyConstraint("run_id", "instrument_id", "path_index", "step", name="path_value_pk"),
    ForeignKeyConstraint(
        ["run_id", "instrument_id"],
        ["run_instrument.run_id", "run_instrument.instrument_id"],
        name="path_value_run_instrument",
        ondelete="CASCADE",
    ),
    CheckConstraint("path_index >= 0 AND step >= 1", name="path_value_index_and_step"),
    CheckConstraint("price > 0", name="path_value_price_positive"),
    Index("path_value_by_step", "run_id", "instrument_id", "step", "path_index"),
)

path_quantile = Table(
    "path_quantile",
    metadata,
    Column("run_id", Uuid, nullable=False),
    Column("instrument_id", Uuid, nullable=False),
    Column("step", Integer, nullable=False),
    Column("q01", PRICE, nullable=False),
    Column("q05", PRICE, nullable=False),
    Column("q25", PRICE, nullable=False),
    Column("q50", PRICE, nullable=False),
    Column("q75", PRICE, nullable=False),
    Column("q95", PRICE, nullable=False),
    Column("q99", PRICE, nullable=False),
    PrimaryKeyConstraint("run_id", "instrument_id", "step", name="path_quantile_pk"),
    ForeignKeyConstraint(
        ["run_id", "instrument_id"],
        ["run_instrument.run_id", "run_instrument.instrument_id"],
        name="path_quantile_run_instrument",
        ondelete="CASCADE",
    ),
    CheckConstraint("step >= 1", name="path_quantile_step"),
    CheckConstraint(
        "q01 > 0 AND q01 <= q05 AND q05 <= q25 AND q25 <= q50"
        " AND q50 <= q75 AND q75 <= q95 AND q95 <= q99",
        name="path_quantile_ordered",
    ),
)

# References that are deliberately not foreign keys (instrument_ref is a display cache of the
# market service's instruments); drawn as dotted lines in the ERD, keyed (parent, child)
LOGICAL_REFERENCES = {
    ("instrument_ref", "calibration"): "instrument_id",
    ("instrument_ref", "run_instrument"): "instrument_id",
}
