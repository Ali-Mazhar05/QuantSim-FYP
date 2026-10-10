"""Instrument master, ingestion runs, bars, quality records, returns, replay sessions,
event outbox, processed events and the audit trail.

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from qs_template.audit import AUDIT_SETUP_STATEMENTS, audit_table_statements

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

PRICE = sa.Numeric(23, 8)
VOLUME = sa.Numeric(28, 8)
FACTOR = sa.Numeric(20, 10)


def _created_at(name: str = "created_at") -> "sa.Column[object]":
    return sa.Column(name, sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())


def upgrade() -> None:
    # In deployed environments db-init creates the extension as a superuser and this is a
    # no-op; in the CI migration check the database user is a superuser and creates it.
    op.execute(
        "DO $$ BEGIN"
        " IF NOT EXISTS (SELECT FROM pg_extension WHERE extname = 'timescaledb') THEN"
        " CREATE EXTENSION timescaledb;"
        " END IF;"
        " END $$"
    )

    op.create_table(
        "instrument",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("exchange", sa.Text(), nullable=False),
        sa.Column("calendar", sa.Text(), nullable=False),
        sa.Column("currency", sa.Text(), nullable=False),
        sa.Column("asset_class", sa.Text(), nullable=False),
        sa.Column("vendor_symbol", sa.Text(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column("is_fixture", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        _created_at(),
        _created_at("updated_at"),
        sa.Column("retired_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("status IN ('active', 'retired')", name="instrument_status_valid"),
        sa.CheckConstraint(
            "(status = 'active' AND retired_at IS NULL)"
            " OR (status = 'retired' AND retired_at IS NOT NULL)",
            name="instrument_retirement_consistent",
        ),
        sa.CheckConstraint("symbol ~ '^[A-Z0-9.-]{1,15}$'", name="instrument_symbol_format"),
        sa.CheckConstraint("exchange ~ '^[A-Z0-9]{4}$'", name="instrument_exchange_format"),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name="instrument_currency_format"),
        sa.CheckConstraint("asset_class IN ('equity', 'etf')", name="instrument_asset_class_valid"),
        sa.UniqueConstraint("symbol", "exchange", name="instrument_symbol_exchange_unique"),
    )

    op.create_table(
        "ingestion_run",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("vendor", sa.Text(), nullable=False),
        sa.Column("requested_by", sa.Text(), nullable=False),
        sa.Column("window_start", sa.Date()),
        sa.Column("window_end", sa.Date()),
        sa.Column("instrument_ids", postgresql.JSONB()),
        sa.Column("ruleset_version", sa.Text()),
        sa.Column("report", postgresql.JSONB()),
        sa.Column("error", sa.Text()),
        sa.Column("idempotency_key", sa.Text()),
        _created_at(),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "mode IN ('daily', 'catchup', 'manual', 'backfill')", name="ingestion_run_mode_valid"
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'partially_succeeded', 'failed')",
            name="ingestion_run_status_valid",
        ),
        sa.CheckConstraint(
            "window_start IS NULL OR window_end IS NULL OR window_start <= window_end",
            name="ingestion_run_window_ordered",
        ),
        sa.CheckConstraint(
            "mode <> 'backfill' OR window_start IS NOT NULL",
            name="ingestion_run_backfill_has_start",
        ),
        sa.UniqueConstraint("idempotency_key", name="ingestion_run_idempotency_key_unique"),
    )
    op.create_index(
        "ingestion_run_pending",
        "ingestion_run",
        ["created_at"],
        postgresql_where=sa.text("status = 'pending'"),
    )

    op.create_table(
        "ingestion_run_item",
        sa.Column(
            "run_id",
            sa.Uuid(),
            sa.ForeignKey("ingestion_run.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("instrument_id", sa.Uuid(), sa.ForeignKey("instrument.id"), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        *(
            sa.Column(name, sa.Integer(), nullable=False, server_default=sa.text("0"))
            for name in (
                "received",
                "passed_untouched",
                "corrected",
                "duplicates_removed",
                "rejected",
                "new_bars",
                "revised",
                "gaps_opened",
                "gaps_resolved",
            )
        ),
        sa.Column("error", sa.Text()),
        sa.PrimaryKeyConstraint("run_id", "instrument_id"),
        sa.CheckConstraint(
            "status IN ('succeeded', 'no_data', 'deferred', 'failed')",
            name="ingestion_run_item_status_valid",
        ),
        sa.CheckConstraint(
            "received >= 0 AND passed_untouched >= 0 AND corrected >= 0"
            " AND duplicates_removed >= 0 AND rejected >= 0 AND new_bars >= 0 AND revised >= 0"
            " AND gaps_opened >= 0 AND gaps_resolved >= 0",
            name="ingestion_run_item_counts_non_negative",
        ),
        sa.CheckConstraint(
            "received = passed_untouched + corrected + duplicates_removed + rejected",
            name="ingestion_run_item_reconciles",
        ),
    )

    op.create_table(
        "staging_bar",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column(
            "run_id",
            sa.Uuid(),
            sa.ForeignKey("ingestion_run.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("instrument_id", sa.Uuid(), sa.ForeignKey("instrument.id"), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        _created_at("received_at"),
    )
    op.create_index("staging_bar_received_at", "staging_bar", ["received_at"])

    op.create_table(
        "bar",
        sa.Column("instrument_id", sa.Uuid(), sa.ForeignKey("instrument.id"), nullable=False),
        sa.Column("session_date", sa.Date(), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("open", PRICE, nullable=False),
        sa.Column("high", PRICE, nullable=False),
        sa.Column("low", PRICE, nullable=False),
        sa.Column("close", PRICE, nullable=False),
        sa.Column("volume", VOLUME, nullable=False),
        sa.Column("adj_open", PRICE),
        sa.Column("adj_high", PRICE),
        sa.Column("adj_low", PRICE),
        sa.Column("adj_close", PRICE),
        sa.Column("adj_volume", VOLUME),
        sa.Column("split_factor", FACTOR, nullable=False, server_default=sa.text("1")),
        sa.Column("dividend", PRICE, nullable=False, server_default=sa.text("0")),
        sa.Column("revision", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column(
            "quality_flags",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("vendor", sa.Text(), nullable=False),
        sa.Column("ruleset_version", sa.Text(), nullable=False),
        _created_at("updated_at"),
        sa.PrimaryKeyConstraint("instrument_id", "session_date"),
        sa.CheckConstraint(
            "open > 0 AND high > 0 AND low > 0 AND close > 0", name="bar_prices_positive"
        ),
        sa.CheckConstraint("low <= high", name="bar_low_not_above_high"),
        sa.CheckConstraint(
            "open BETWEEN low AND high AND close BETWEEN low AND high",
            name="bar_open_close_in_range",
        ),
        sa.CheckConstraint("volume >= 0", name="bar_volume_non_negative"),
        sa.CheckConstraint(
            "(adj_open IS NULL OR adj_open > 0) AND (adj_high IS NULL OR adj_high > 0)"
            " AND (adj_low IS NULL OR adj_low > 0) AND (adj_close IS NULL OR adj_close > 0)",
            name="bar_adjusted_prices_positive",
        ),
        sa.CheckConstraint("split_factor > 0", name="bar_split_factor_positive"),
        sa.CheckConstraint("dividend >= 0", name="bar_dividend_non_negative"),
        sa.CheckConstraint("revision >= 1", name="bar_revision_positive"),
    )

    op.create_table(
        "bar_revision",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("instrument_id", sa.Uuid(), nullable=False),
        sa.Column("session_date", sa.Date(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("previous", postgresql.JSONB(), nullable=False),
        sa.Column("superseded_by_run", sa.Uuid(), nullable=False),
        _created_at("superseded_at"),
        sa.UniqueConstraint(
            "instrument_id", "session_date", "revision", name="bar_revision_unique"
        ),
    )

    op.create_table(
        "rejected_bar",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column(
            "run_id",
            sa.Uuid(),
            sa.ForeignKey("ingestion_run.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("instrument_id", sa.Uuid(), sa.ForeignKey("instrument.id"), nullable=False),
        sa.Column("session_date", sa.Date()),
        sa.Column("rules", postgresql.JSONB(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        _created_at("rejected_at"),
    )
    op.create_index("rejected_bar_run", "rejected_bar", ["run_id"])

    op.create_table(
        "data_gap",
        sa.Column("instrument_id", sa.Uuid(), sa.ForeignKey("instrument.id"), nullable=False),
        sa.Column("session_date", sa.Date(), nullable=False),
        sa.Column("opened_by_run", sa.Uuid(), nullable=False),
        _created_at("opened_at"),
        sa.Column("resolved_by_run", sa.Uuid()),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint("instrument_id", "session_date"),
        sa.CheckConstraint(
            "(resolved_at IS NULL) = (resolved_by_run IS NULL)",
            name="data_gap_resolution_consistent",
        ),
    )
    op.create_index(
        "data_gap_open",
        "data_gap",
        ["instrument_id"],
        postgresql_where=sa.text("resolved_at IS NULL"),
    )

    op.create_table(
        "corporate_action",
        sa.Column("instrument_id", sa.Uuid(), sa.ForeignKey("instrument.id"), nullable=False),
        sa.Column("session_date", sa.Date(), nullable=False),
        sa.Column("split_factor", FACTOR, nullable=False, server_default=sa.text("1")),
        sa.Column("dividend", PRICE, nullable=False, server_default=sa.text("0")),
        sa.Column("vendor", sa.Text(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("instrument_id", "session_date"),
        sa.CheckConstraint("split_factor > 0", name="corporate_action_split_positive"),
        sa.CheckConstraint("dividend >= 0", name="corporate_action_dividend_non_negative"),
        sa.CheckConstraint("split_factor <> 1 OR dividend > 0", name="corporate_action_not_empty"),
    )

    op.create_table(
        "return_series",
        sa.Column("instrument_id", sa.Uuid(), sa.ForeignKey("instrument.id"), nullable=False),
        sa.Column("session_date", sa.Date(), nullable=False),
        sa.Column("log_return", sa.Float()),
        sa.Column("adj_log_return", sa.Float()),
        sa.Column("vol_20d", sa.Float()),
        sa.Column("vol_60d", sa.Float()),
        _created_at("computed_at"),
        sa.PrimaryKeyConstraint("instrument_id", "session_date"),
    )

    op.create_table(
        "replay_session",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("instrument_ids", postgresql.JSONB(), nullable=False),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("speed", sa.Float(), nullable=False, server_default=sa.text("1")),
        sa.Column("status", sa.Text(), nullable=False, server_default="created"),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        _created_at(),
        sa.CheckConstraint("end_time > start_time", name="replay_session_window_valid"),
        sa.CheckConstraint("speed > 0 AND speed <= 1000", name="replay_session_speed_valid"),
        sa.CheckConstraint(
            "status IN ('created', 'playing', 'paused', 'finished')",
            name="replay_session_status_valid",
        ),
        sa.CheckConstraint(
            "char_length(name) BETWEEN 1 AND 120", name="replay_session_name_length"
        ),
    )

    # Bars and returns are time series: TimescaleDB partitions them by session. The
    # primary keys already index (instrument, session), so no default time index.
    for table in ("bar", "return_series"):
        op.execute(
            f"SELECT create_hypertable('{table}', by_range('session_date', INTERVAL '1 year'),"
            " create_default_indexes => false)"
        )

    op.create_table(
        "outbox",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("event_id", sa.Uuid(), nullable=False, unique=True),
        sa.Column("topic", sa.Text(), nullable=False),
        sa.Column("message_key", sa.Text(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        _created_at(),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("last_error", sa.Text()),
    )
    op.create_index(
        "outbox_pending", "outbox", ["id"], postgresql_where=sa.text("published_at IS NULL")
    )

    op.create_table(
        "processed_events",
        sa.Column("consumer_group", sa.Text(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        _created_at("processed_at"),
        sa.PrimaryKeyConstraint("consumer_group", "event_id"),
    )

    for statement in AUDIT_SETUP_STATEMENTS:
        op.execute(statement)
    for statement in audit_table_statements("instrument"):
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS instrument_audit ON instrument")
    for table in (
        "processed_events",
        "outbox",
        "replay_session",
        "return_series",
        "corporate_action",
        "data_gap",
        "rejected_bar",
        "bar_revision",
        "bar",
        "staging_bar",
        "ingestion_run_item",
        "ingestion_run",
        "instrument",
    ):
        op.drop_table(table)
    op.execute("DROP TRIGGER IF EXISTS audit_log_append_only ON audit_log")
    op.execute("DROP TABLE IF EXISTS audit_log")
    op.execute("DROP FUNCTION IF EXISTS qs_audit_log_is_append_only()")
    op.execute("DROP FUNCTION IF EXISTS qs_audit_row()")
    # The timescaledb extension stays: db-init owns it, not this migration
