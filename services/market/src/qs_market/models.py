"""Tables of ``market_db``. The migrations in ``migrations/`` create exactly these; a test
compares the two.

Prices are fixed-precision decimals with 8 decimal places, never floating point
(NFR-INT-001). ``bar`` and ``return_series`` are TimescaleDB hypertables, created by the
migration. The database refuses impossible data on its own (impossible bars, an inverted
replay window, a run report that does not add up), so no code path can store it.
"""

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Identity,
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

metadata = MetaData()

PRICE = Numeric(23, 8)
# The vendor restates adjusted prices with ten decimals; storing eight would round them
ADJUSTED_PRICE = Numeric(23, 10)
VOLUME = Numeric(28, 8)
FACTOR = Numeric(20, 10)
# Returns and volatility are small ratios; kept exact like every other stored number
RATIO = Numeric(20, 12)

ASSET_CLASSES = ("equity", "etf")
RUN_MODES = ("daily", "catchup", "manual", "backfill")
RUN_STATUSES = ("pending", "running", "succeeded", "partially_succeeded", "failed")
RUN_ITEM_STATUSES = ("succeeded", "no_data", "deferred", "failed")
# Market environments use exactly the POC's values (lower-case in the API and database)
ENVIRONMENT_TYPES = ("historical_replay", "synthetic")
ENVIRONMENT_FREQUENCIES = ("daily", "hourly", "tick")
ENVIRONMENT_STATUSES = ("draft", "ready", "active")


def _one_of(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


instrument = Table(
    "instrument",
    metadata,
    Column("id", Uuid, primary_key=True, server_default=text("gen_random_uuid()")),
    Column("symbol", Text, nullable=False),
    Column("name", Text, nullable=False),
    Column("sector", Text, nullable=False),  # shown on the POC Instruments page
    Column("exchange", Text, nullable=False),  # ISO 10383 MIC, e.g. XNAS
    Column("calendar", Text, nullable=False),  # trading calendar code, e.g. XNYS
    Column("currency", Text, nullable=False),
    Column("asset_class", Text, nullable=False),
    Column("vendor_symbol", Text, nullable=False),
    Column("notes", Text, nullable=False, server_default=""),
    Column("status", Text, nullable=False, server_default="active"),
    # Planted-fault instruments fed by the fixture vendor; kept out of real quality totals
    Column("is_fixture", Boolean, nullable=False, server_default=text("false")),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("retired_at", DateTime(timezone=True)),
    CheckConstraint("status IN ('active', 'retired')", name="instrument_status_valid"),
    CheckConstraint(
        "(status = 'active' AND retired_at IS NULL)"
        " OR (status = 'retired' AND retired_at IS NOT NULL)",
        name="instrument_retirement_consistent",
    ),
    CheckConstraint("symbol ~ '^[A-Z0-9.-]{1,15}$'", name="instrument_symbol_format"),
    CheckConstraint("exchange ~ '^[A-Z0-9]{4}$'", name="instrument_exchange_format"),
    CheckConstraint("currency ~ '^[A-Z]{3}$'", name="instrument_currency_format"),
    CheckConstraint("char_length(sector) BETWEEN 1 AND 80", name="instrument_sector_length"),
    CheckConstraint(_one_of("asset_class", ASSET_CLASSES), name="instrument_asset_class_valid"),
    UniqueConstraint("symbol", "exchange", name="instrument_symbol_exchange_unique"),
)

ingestion_run = Table(
    "ingestion_run",
    metadata,
    Column("id", Uuid, primary_key=True, server_default=text("gen_random_uuid()")),
    Column("mode", Text, nullable=False),
    Column("status", Text, nullable=False, server_default="pending"),
    Column("vendor", Text, nullable=False),
    Column("requested_by", Text, nullable=False),  # a user id, or "scheduler"
    Column("window_start", Date),
    Column("window_end", Date),
    Column("instrument_ids", JSONB),  # null means every active instrument
    Column("ruleset_version", Text),
    Column("report", JSONB),  # the reconciliation report, once the run ends
    Column("error", Text),
    # Scheduled runs use one key per mode and date, so two schedulers create one run
    Column("idempotency_key", Text),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("started_at", DateTime(timezone=True)),
    Column("finished_at", DateTime(timezone=True)),
    CheckConstraint(_one_of("mode", RUN_MODES), name="ingestion_run_mode_valid"),
    CheckConstraint(_one_of("status", RUN_STATUSES), name="ingestion_run_status_valid"),
    CheckConstraint(
        "window_start IS NULL OR window_end IS NULL OR window_start <= window_end",
        name="ingestion_run_window_ordered",
    ),
    CheckConstraint(
        "mode <> 'backfill' OR window_start IS NOT NULL", name="ingestion_run_backfill_has_start"
    ),
    UniqueConstraint("idempotency_key", name="ingestion_run_idempotency_key_unique"),
    Index("ingestion_run_pending", "created_at", postgresql_where=text("status = 'pending'")),
)

ingestion_run_item = Table(
    "ingestion_run_item",
    metadata,
    Column("run_id", Uuid, ForeignKey("ingestion_run.id", ondelete="CASCADE"), nullable=False),
    Column("instrument_id", Uuid, ForeignKey("instrument.id"), nullable=False),
    Column("status", Text, nullable=False),
    Column("received", Integer, nullable=False, server_default=text("0")),
    Column("passed_untouched", Integer, nullable=False, server_default=text("0")),
    Column("corrected", Integer, nullable=False, server_default=text("0")),
    Column("duplicates_removed", Integer, nullable=False, server_default=text("0")),
    Column("rejected", Integer, nullable=False, server_default=text("0")),
    Column("new_bars", Integer, nullable=False, server_default=text("0")),
    Column("revised", Integer, nullable=False, server_default=text("0")),
    Column("gaps_opened", Integer, nullable=False, server_default=text("0")),
    Column("gaps_resolved", Integer, nullable=False, server_default=text("0")),
    Column("error", Text),
    PrimaryKeyConstraint("run_id", "instrument_id"),
    CheckConstraint(_one_of("status", RUN_ITEM_STATUSES), name="ingestion_run_item_status_valid"),
    CheckConstraint(
        "received >= 0 AND passed_untouched >= 0 AND corrected >= 0"
        " AND duplicates_removed >= 0 AND rejected >= 0 AND new_bars >= 0 AND revised >= 0"
        " AND gaps_opened >= 0 AND gaps_resolved >= 0",
        name="ingestion_run_item_counts_non_negative",
    ),
    # The reconciliation report always adds up (FR-26)
    CheckConstraint(
        "received = passed_untouched + corrected + duplicates_removed + rejected",
        name="ingestion_run_item_reconciles",
    ),
)

staging_bar = Table(
    "staging_bar",
    metadata,
    Column("id", BigInteger, Identity(always=True), primary_key=True),
    Column("run_id", Uuid, ForeignKey("ingestion_run.id", ondelete="CASCADE"), nullable=False),
    Column("instrument_id", Uuid, ForeignKey("instrument.id"), nullable=False),
    Column("payload", JSONB, nullable=False),  # the vendor record, untouched
    Column("received_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Index("staging_bar_received_at", "received_at"),
)

bar = Table(
    "bar",
    metadata,
    Column("instrument_id", Uuid, ForeignKey("instrument.id"), nullable=False),
    Column("session_date", Date, nullable=False),
    Column("ts", DateTime(timezone=True), nullable=False),  # the session's close, UTC
    Column("open", PRICE, nullable=False),
    Column("high", PRICE, nullable=False),
    Column("low", PRICE, nullable=False),
    Column("close", PRICE, nullable=False),
    Column("volume", VOLUME, nullable=False),
    # Split- and dividend-adjusted values as the vendor reports them (FR-28)
    Column("adj_open", ADJUSTED_PRICE),
    Column("adj_high", ADJUSTED_PRICE),
    Column("adj_low", ADJUSTED_PRICE),
    Column("adj_close", ADJUSTED_PRICE),
    Column("adj_volume", VOLUME),
    Column("split_factor", FACTOR, nullable=False, server_default=text("1")),
    Column("dividend", PRICE, nullable=False, server_default=text("0")),
    Column("revision", Integer, nullable=False, server_default=text("1")),
    Column("content_hash", Text, nullable=False),
    Column("quality_flags", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    # Provenance of the current revision (FR-29)
    Column("run_id", Uuid, nullable=False),
    Column("vendor", Text, nullable=False),
    Column("ruleset_version", Text, nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    PrimaryKeyConstraint("instrument_id", "session_date"),
    CheckConstraint("open > 0 AND high > 0 AND low > 0 AND close > 0", name="bar_prices_positive"),
    CheckConstraint("low <= high", name="bar_low_not_above_high"),
    CheckConstraint(
        "open BETWEEN low AND high AND close BETWEEN low AND high", name="bar_open_close_in_range"
    ),
    CheckConstraint("volume >= 0", name="bar_volume_non_negative"),
    CheckConstraint(
        "(adj_open IS NULL OR adj_open > 0) AND (adj_high IS NULL OR adj_high > 0)"
        " AND (adj_low IS NULL OR adj_low > 0) AND (adj_close IS NULL OR adj_close > 0)",
        name="bar_adjusted_prices_positive",
    ),
    CheckConstraint("split_factor > 0", name="bar_split_factor_positive"),
    CheckConstraint("dividend >= 0", name="bar_dividend_non_negative"),
    CheckConstraint("revision >= 1", name="bar_revision_positive"),
)

bar_revision = Table(
    "bar_revision",
    metadata,
    Column("id", BigInteger, Identity(always=True), primary_key=True),
    Column("instrument_id", Uuid, nullable=False),
    Column("session_date", Date, nullable=False),
    Column("revision", Integer, nullable=False),  # the revision this row preserves
    Column("previous", JSONB, nullable=False),  # the bar as it was, provenance included
    Column("superseded_by_run", Uuid, nullable=False),
    Column("superseded_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("instrument_id", "session_date", "revision", name="bar_revision_unique"),
)

rejected_bar = Table(
    "rejected_bar",
    metadata,
    Column("id", BigInteger, Identity(always=True), primary_key=True),
    Column("run_id", Uuid, ForeignKey("ingestion_run.id", ondelete="CASCADE"), nullable=False),
    Column("instrument_id", Uuid, ForeignKey("instrument.id"), nullable=False),
    Column("session_date", Date),  # null when the record's date could not be read
    Column("rules", JSONB, nullable=False),  # every rule it broke
    Column("payload", JSONB, nullable=False),
    Column("rejected_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Index("rejected_bar_run", "run_id"),
)

data_gap = Table(
    "data_gap",
    metadata,
    Column("instrument_id", Uuid, ForeignKey("instrument.id"), nullable=False),
    Column("session_date", Date, nullable=False),
    Column("opened_by_run", Uuid, nullable=False),
    Column("opened_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("resolved_by_run", Uuid),
    Column("resolved_at", DateTime(timezone=True)),
    PrimaryKeyConstraint("instrument_id", "session_date"),
    CheckConstraint(
        "(resolved_at IS NULL) = (resolved_by_run IS NULL)", name="data_gap_resolution_consistent"
    ),
    Index("data_gap_open", "instrument_id", postgresql_where=text("resolved_at IS NULL")),
)

corporate_action = Table(
    "corporate_action",
    metadata,
    Column("instrument_id", Uuid, ForeignKey("instrument.id"), nullable=False),
    Column("session_date", Date, nullable=False),
    Column("split_factor", FACTOR, nullable=False, server_default=text("1")),
    Column("dividend", PRICE, nullable=False, server_default=text("0")),
    Column("vendor", Text, nullable=False),
    Column("run_id", Uuid, nullable=False),
    PrimaryKeyConstraint("instrument_id", "session_date"),
    CheckConstraint("split_factor > 0", name="corporate_action_split_positive"),
    CheckConstraint("dividend >= 0", name="corporate_action_dividend_non_negative"),
    CheckConstraint("split_factor <> 1 OR dividend > 0", name="corporate_action_not_empty"),
)

return_series = Table(
    "return_series",
    metadata,
    Column("instrument_id", Uuid, ForeignKey("instrument.id"), nullable=False),
    Column("session_date", Date, nullable=False),
    Column("log_return", RATIO),
    Column("adj_log_return", RATIO),
    Column("vol_20d", RATIO),
    Column("vol_60d", RATIO),
    Column("computed_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    PrimaryKeyConstraint("instrument_id", "session_date"),
)

# A market a simulation or portfolio runs inside, shaped like the POC's Market
# Environments pages (FR-30). Replay playback state arrives with Iteration 2.
market_environment = Table(
    "market_environment",
    metadata,
    Column("id", Uuid, primary_key=True, server_default=text("gen_random_uuid()")),
    Column("name", Text, nullable=False),
    Column("type", Text, nullable=False),
    Column("universe", Text, nullable=False),
    Column("instrument_ids", JSONB, nullable=False),
    Column("start_date", Date, nullable=False),
    Column("end_date", Date, nullable=False),
    Column("frequency", Text, nullable=False, server_default="daily"),
    Column("status", Text, nullable=False, server_default="draft"),
    Column("created_by", Uuid, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    # FR-MKT-008 / NFR-INT-003: the database itself refuses an inverted window
    CheckConstraint("end_date > start_date", name="market_environment_window_valid"),
    CheckConstraint(_one_of("type", ENVIRONMENT_TYPES), name="market_environment_type_valid"),
    CheckConstraint(
        _one_of("frequency", ENVIRONMENT_FREQUENCIES), name="market_environment_frequency_valid"
    ),
    CheckConstraint(
        _one_of("status", ENVIRONMENT_STATUSES), name="market_environment_status_valid"
    ),
    CheckConstraint("char_length(name) BETWEEN 1 AND 120", name="market_environment_name_length"),
    CheckConstraint(
        "char_length(universe) BETWEEN 1 AND 120", name="market_environment_universe_length"
    ),
    CheckConstraint(
        "jsonb_typeof(instrument_ids) = 'array'"
        " AND jsonb_array_length(instrument_ids) BETWEEN 1 AND 100",
        name="market_environment_instrument_count",
    ),
)

# Tables whose every change is written to the audit log (FR-PLT-006)
AUDITED_TABLES = ("instrument",)
# References that are deliberately not foreign keys (hypertables and append-only history
# rows keep no foreign keys); drawn as dotted lines in the ERD, keyed (parent, child)
LOGICAL_REFERENCES = {
    ("ingestion_run", "bar"): "run_id",
    ("bar", "bar_revision"): "instrument_id + session_date",
    ("ingestion_run", "bar_revision"): "superseded_by_run",
    ("ingestion_run", "data_gap"): "opened_by_run / resolved_by_run",
    ("ingestion_run", "corporate_action"): "run_id",
}
# Partition column of each hypertable
HYPERTABLES = {"bar": "session_date", "return_series": "session_date"}
