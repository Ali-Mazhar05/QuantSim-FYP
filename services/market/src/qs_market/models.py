"""Tables of ``market_db``. The migrations in ``migrations/`` create exactly these.

Prices are fixed-precision decimals, never floating point (NFR-INT-001). ``bar`` and
``return_series`` become TimescaleDB hypertables in the migration.
"""

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Float,
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

PRICE = Numeric(20, 6)
VOLUME = Numeric(28, 8)

instrument = Table(
    "instrument",
    metadata,
    Column("id", Uuid, primary_key=True, server_default=text("gen_random_uuid()")),
    Column("symbol", Text, nullable=False),
    Column("name", Text, nullable=False),
    Column("exchange", Text, nullable=False),  # ISO 10383 MIC, e.g. XNAS
    Column("calendar", Text, nullable=False),  # exchange_calendars code, e.g. XNYS
    Column("currency", Text, nullable=False),
    Column("asset_class", Text, nullable=False),
    Column("vendor_symbol", Text, nullable=False),
    Column("notes", Text, nullable=False, server_default=""),
    Column("status", Text, nullable=False, server_default="active"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("retired_at", DateTime(timezone=True)),
    CheckConstraint("status IN ('active', 'retired')", name="instrument_status_valid"),
    CheckConstraint(
        "(status = 'active' AND retired_at IS NULL) OR (status = 'retired' AND retired_at IS NOT NULL)",
        name="instrument_retirement_consistent",
    ),
    CheckConstraint("symbol ~ '^[A-Z0-9.\\-]{1,15}$'", name="instrument_symbol_format"),
    CheckConstraint("currency ~ '^[A-Z]{3}$'", name="instrument_currency_format"),
    CheckConstraint(
        "asset_class IN ('equity', 'etf', 'index', 'crypto', 'fx')",
        name="instrument_asset_class_valid",
    ),
    UniqueConstraint("symbol", "exchange", name="instrument_symbol_exchange_unique"),
)

ingestion_run = Table(
    "ingestion_run",
    metadata,
    Column("id", Uuid, primary_key=True, server_default=text("gen_random_uuid()")),
    Column("source", Text, nullable=False),
    Column("mode", Text, nullable=False),
    Column("status", Text, nullable=False, server_default="pending"),
    Column("requested_by", Text, nullable=False),
    Column("window_start", Date),
    Column("window_end", Date),
    Column("instrument_ids", JSONB),  # null = every active instrument
    Column("ruleset_version", Text),
    Column("report", JSONB),
    Column("error", Text),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("started_at", DateTime(timezone=True)),
    Column("finished_at", DateTime(timezone=True)),
    # Duplicate scheduled runs collapse onto one row
    Column("idempotency_key", Text, unique=True),
    CheckConstraint("mode IN ('daily', 'catchup', 'backfill', 'manual')", name="run_mode_valid"),
    CheckConstraint(
        "status IN ('pending', 'running', 'succeeded', 'partially_succeeded', 'failed', 'skipped')",
        name="run_status_valid",
    ),
    CheckConstraint(
        "window_start IS NULL OR window_end IS NULL OR window_start <= window_end",
        name="run_window_ordered",
    ),
    Index("ingestion_run_pending", "created_at", postgresql_where=text("status = 'pending'")),
)

ingestion_run_item = Table(
    "ingestion_run_item",
    metadata,
    Column("run_id", Uuid, ForeignKey("ingestion_run.id", ondelete="CASCADE"), nullable=False),
    Column("instrument_id", Uuid, ForeignKey("instrument.id"), nullable=False),
    Column("status", Text, nullable=False),
    Column("fetched", Integer, nullable=False, server_default=text("0")),
    Column("passed", Integer, nullable=False, server_default=text("0")),
    Column("corrected", Integer, nullable=False, server_default=text("0")),
    Column("rejected", Integer, nullable=False, server_default=text("0")),
    Column("revised", Integer, nullable=False, server_default=text("0")),
    Column("gaps", Integer, nullable=False, server_default=text("0")),
    Column("error", Text),
    PrimaryKeyConstraint("run_id", "instrument_id"),
    CheckConstraint(
        "status IN ('succeeded', 'failed', 'deferred', 'no_data')", name="run_item_status_valid"
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
)

bar = Table(
    "bar",
    metadata,
    Column("instrument_id", Uuid, ForeignKey("instrument.id"), nullable=False),
    Column("session_date", Date, nullable=False),
    Column("ts", DateTime(timezone=True), nullable=False),  # session close, UTC
    Column("open", PRICE, nullable=False),
    Column("high", PRICE, nullable=False),
    Column("low", PRICE, nullable=False),
    Column("close", PRICE, nullable=False),
    Column("volume", VOLUME, nullable=False),
    Column("adj_close", PRICE),
    Column("split_factor", Numeric(20, 10), nullable=False, server_default=text("1")),
    Column("dividend", PRICE, nullable=False, server_default=text("0")),
    Column("source", Text, nullable=False),
    Column("revision", Integer, nullable=False, server_default=text("1")),
    Column("content_hash", Text, nullable=False),
    Column("quality_flags", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    Column("run_id", Uuid, nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    PrimaryKeyConstraint("instrument_id", "session_date"),
    # The database refuses impossible bars even if a code path forgets to check
    CheckConstraint("open > 0 AND high > 0 AND low > 0 AND close > 0", name="bar_prices_positive"),
    CheckConstraint("low <= high", name="bar_low_le_high"),
    CheckConstraint("open BETWEEN low AND high AND close BETWEEN low AND high", name="bar_ohlc_in_range"),
    CheckConstraint("volume >= 0", name="bar_volume_non_negative"),
    CheckConstraint("revision >= 1", name="bar_revision_positive"),
)

bar_revision = Table(
    "bar_revision",
    metadata,
    Column("id", BigInteger, Identity(always=True), primary_key=True),
    Column("instrument_id", Uuid, nullable=False),
    Column("session_date", Date, nullable=False),
    Column("revision", Integer, nullable=False),
    Column("previous", JSONB, nullable=False),  # the bar as it was before the correction
    Column("run_id", Uuid, nullable=False),
    Column("superseded_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Index("bar_revision_bar", "instrument_id", "session_date"),
)

rejected_bar = Table(
    "rejected_bar",
    metadata,
    Column("id", BigInteger, Identity(always=True), primary_key=True),
    Column("run_id", Uuid, ForeignKey("ingestion_run.id", ondelete="CASCADE"), nullable=False),
    Column("instrument_id", Uuid, ForeignKey("instrument.id"), nullable=False),
    Column("session_date", Date),
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
    Column("first_seen_run", Uuid, nullable=False),
    Column("resolved_at", DateTime(timezone=True)),
    PrimaryKeyConstraint("instrument_id", "session_date"),
)

corporate_action = Table(
    "corporate_action",
    metadata,
    Column("instrument_id", Uuid, ForeignKey("instrument.id"), nullable=False),
    Column("session_date", Date, nullable=False),
    Column("split_factor", Numeric(20, 10), nullable=False, server_default=text("1")),
    Column("dividend", PRICE, nullable=False, server_default=text("0")),
    Column("source", Text, nullable=False),
    PrimaryKeyConstraint("instrument_id", "session_date"),
    CheckConstraint("split_factor > 0", name="corporate_action_split_positive"),
)

return_series = Table(
    "return_series",
    metadata,
    Column("instrument_id", Uuid, ForeignKey("instrument.id"), nullable=False),
    Column("session_date", Date, nullable=False),
    # Returns are ratios, not money, so floating point is appropriate here
    Column("log_return", Float),
    Column("adj_log_return", Float),
    Column("vol_20d", Float),
    Column("vol_60d", Float),
    Column("computed_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    PrimaryKeyConstraint("instrument_id", "session_date"),
)

replay_session = Table(
    "replay_session",
    metadata,
    Column("id", Uuid, primary_key=True, server_default=text("gen_random_uuid()")),
    Column("name", Text, nullable=False),
    Column("instrument_ids", JSONB, nullable=False),
    Column("start_time", DateTime(timezone=True), nullable=False),
    Column("end_time", DateTime(timezone=True), nullable=False),
    Column("speed", Float, nullable=False, server_default=text("1")),
    Column("status", Text, nullable=False, server_default="created"),
    Column("created_by", Uuid, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    # FR-MKT-008 / NFR-INT-003: the database itself refuses an inverted window
    CheckConstraint("end_time > start_time", name="replay_session_window_valid"),
    CheckConstraint("speed > 0 AND speed <= 1000", name="replay_session_speed_valid"),
    CheckConstraint(
        "status IN ('created', 'playing', 'paused', 'finished')", name="replay_session_status_valid"
    ),
)
