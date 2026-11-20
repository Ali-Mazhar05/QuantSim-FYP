"""trading_db schema: strategies, portfolios, orders, fills, the append-only trade log and
its projections (A13, A-FR-04, A-FR-10).

The trade log is a TimescaleDB hypertable, so a unique index on ``(portfolio_id, seq)``
alone is not possible (every unique index must include ``event_time``). A trigger
enforces it instead: each insert takes a per-portfolio transaction lock and must carry
``seq = last seq + 1``, so a repeated seq and a gap are both refused. A second trigger
refuses UPDATE and DELETE for every role, the owner and superusers included, and the
privileges themselves are revoked from the role that runs the migrations (the service's
own role in deployed environments) and from PUBLIC.

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

PRICE = sa.Numeric(20, 8)
CASH = sa.Numeric(20, 2)
RATIO = sa.Numeric(20, 12)

# Frozen copy of qs_trading.domain.events.EventType at this revision
EVENT_TYPES = (
    "RUN_STARTED",
    "TICK",
    "ORDER_PLACED",
    "ORDER_REJECTED",
    "ORDER_FILLED",
    "ORDER_EXPIRED",
    "VALUED",
    "RUN_COMPLETED",
)

TABLES = (
    "strategy",
    "portfolio",
    "order",
    "fill",
    "trade_event",
    "holding_history",
    "portfolio_value",
    "portfolio_metrics",
    "portfolio_state_current",
    "instrument_ref",
)

# One statement per item: asyncpg runs one statement per call
GUARD_STATEMENTS = (
    # Raises for any row it fires on; TG_ARGV[0] names the table, because on a hypertable
    # the trigger fires on the chunk and TG_TABLE_NAME is the chunk's name
    """
    CREATE OR REPLACE FUNCTION qs_trading_append_only() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        RAISE EXCEPTION '% is append-only: % is not allowed', TG_ARGV[0], TG_OP
            USING ERRCODE = 'insufficient_privilege';
    END;
    $$
    """,
    # Serialises appends per portfolio, then requires seq to follow the last one. Under
    # READ COMMITTED every query in this function sees rows committed before the lock was
    # granted, and rows inserted earlier by the same statement.
    """
    CREATE OR REPLACE FUNCTION qs_trade_event_seq_follows() RETURNS trigger
    LANGUAGE plpgsql AS $$
    DECLARE
        previous bigint;
    BEGIN
        IF NEW.seq IS NULL OR NEW.seq < 1 THEN
            -- Left to the NOT NULL and trade_event_seq_positive constraints
            RETURN NEW;
        END IF;
        PERFORM pg_advisory_xact_lock(
            hashtextextended('qs_trade_event:' || NEW.portfolio_id::text, 0));
        SELECT max(seq) INTO previous FROM trade_event WHERE portfolio_id = NEW.portfolio_id;
        previous := COALESCE(previous, 0);
        IF NEW.seq <= previous THEN
            RAISE EXCEPTION 'trade_event_seq_unique: portfolio % already has seq %',
                NEW.portfolio_id, NEW.seq
                USING ERRCODE = 'unique_violation';
        END IF;
        IF NEW.seq <> previous + 1 THEN
            RAISE EXCEPTION 'trade_event_seq_gap_free: portfolio % expects seq %, got %',
                NEW.portfolio_id, previous + 1, NEW.seq
                USING ERRCODE = 'check_violation';
        END IF;
        RETURN NEW;
    END;
    $$
    """,
)


def _now(name: str) -> "sa.Column[object]":
    return sa.Column(name, sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())


def _empty_object(name: str) -> "sa.Column[object]":
    return sa.Column(
        name, postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
    )


def upgrade() -> None:
    # The timescaledb extension must already exist: db-init creates it as the superuser
    op.create_table(
        "strategy",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        _empty_object("params"),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        _now("created_at"),
        _now("updated_at"),
        sa.CheckConstraint("char_length(name) BETWEEN 1 AND 120", name="strategy_name_length"),
        sa.CheckConstraint("kind ~ '^[a-z][a-z0-9_]{0,39}$'", name="strategy_kind_format"),
        sa.CheckConstraint("jsonb_typeof(params) = 'object'", name="strategy_params_object"),
    )

    op.create_table(
        "portfolio",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("strategy_id", sa.Uuid(), sa.ForeignKey("strategy.id"), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("initial_capital", CASH, nullable=False),
        sa.Column("base_currency", sa.Text(), nullable=False, server_default=sa.text("'USD'")),
        _empty_object("cost_model"),
        _empty_object("slippage_model"),
        sa.Column("env_type", sa.Text(), nullable=False),
        sa.Column("replay_environment_id", sa.Uuid()),
        sa.Column("simulation_run_id", sa.Uuid()),
        sa.Column("path_index", sa.Integer()),
        sa.Column("source_fingerprint", sa.Text()),
        _now("created_at"),
        _now("updated_at"),
        sa.CheckConstraint("char_length(name) BETWEEN 1 AND 120", name="portfolio_name_length"),
        sa.CheckConstraint("initial_capital > 0", name="portfolio_capital_positive"),
        sa.CheckConstraint("base_currency = 'USD'", name="portfolio_base_currency_usd"),
        sa.CheckConstraint("env_type IN ('replay', 'simulation')", name="portfolio_env_type_valid"),
        # Exactly one environment: a replay, or one path of a simulation run (A-FR-04)
        sa.CheckConstraint(
            "(env_type = 'replay' AND replay_environment_id IS NOT NULL"
            " AND simulation_run_id IS NULL AND path_index IS NULL)"
            " OR (env_type = 'simulation' AND simulation_run_id IS NOT NULL"
            " AND replay_environment_id IS NULL AND path_index IS NOT NULL)",
            name="portfolio_environment_binding",
        ),
        sa.CheckConstraint(
            "path_index IS NULL OR path_index >= 0", name="portfolio_path_index_valid"
        ),
        sa.CheckConstraint(
            "jsonb_typeof(cost_model) = 'object' AND jsonb_typeof(slippage_model) = 'object'",
            name="portfolio_models_are_objects",
        ),
        sa.CheckConstraint(
            "source_fingerprint IS NULL OR char_length(source_fingerprint) > 0",
            name="portfolio_fingerprint_not_empty",
        ),
    )

    op.create_table(
        "order",
        sa.Column("portfolio_id", sa.Uuid(), sa.ForeignKey("portfolio.id"), nullable=False),
        sa.Column("order_id", sa.Text(), nullable=False),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("side", sa.Text(), nullable=False),
        sa.Column("quantity", sa.BigInteger(), nullable=False),
        sa.Column("order_type", sa.Text(), nullable=False),
        sa.Column("limit_price", PRICE),
        sa.Column("placed_seq", sa.BigInteger(), nullable=False),
        sa.Column("placed_session", sa.Integer(), nullable=False),
        sa.Column("expires_session", sa.Integer()),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'open'")),
        _now("updated_at"),
        sa.PrimaryKeyConstraint("portfolio_id", "order_id"),
        sa.CheckConstraint("side IN ('buy', 'sell')", name="order_side_valid"),
        sa.CheckConstraint("quantity > 0", name="order_quantity_positive"),
        sa.CheckConstraint("order_type IN ('market', 'limit')", name="order_type_valid"),
        sa.CheckConstraint(
            "(order_type = 'limit') = (limit_price IS NOT NULL)",
            name="order_limit_price_iff_limit",
        ),
        sa.CheckConstraint(
            "limit_price IS NULL OR limit_price > 0", name="order_limit_price_positive"
        ),
        sa.CheckConstraint(
            "order_type = 'limit' OR expires_session IS NULL", name="order_market_never_expires"
        ),
        sa.CheckConstraint(
            "status IN ('open', 'filled', 'rejected', 'expired')", name="order_status_valid"
        ),
        sa.CheckConstraint("placed_seq >= 1 AND placed_session >= 0", name="order_placement_valid"),
    )

    op.create_table(
        "fill",
        sa.Column("portfolio_id", sa.Uuid(), nullable=False),
        sa.Column("seq", sa.BigInteger(), nullable=False),
        sa.Column("order_id", sa.Text(), nullable=False),
        sa.Column("session", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("side", sa.Text(), nullable=False),
        sa.Column("quantity", sa.BigInteger(), nullable=False),
        sa.Column("reference_price", PRICE, nullable=False),
        sa.Column("fill_price", PRICE, nullable=False),
        sa.Column("slippage", PRICE, nullable=False),
        sa.Column("cost_fixed", CASH, nullable=False),
        sa.Column("cost_per_share", CASH, nullable=False),
        sa.Column("cost_percentage", CASH, nullable=False),
        sa.Column("cost_total", CASH, nullable=False),
        sa.Column("cash_after", CASH, nullable=False),
        sa.PrimaryKeyConstraint("portfolio_id", "seq"),
        sa.ForeignKeyConstraint(
            ["portfolio_id", "order_id"],
            ["order.portfolio_id", "order.order_id"],
            name="fill_order_fk",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("seq >= 1 AND session >= 0", name="fill_position_valid"),
        sa.CheckConstraint("side IN ('buy', 'sell')", name="fill_side_valid"),
        sa.CheckConstraint("quantity > 0", name="fill_quantity_positive"),
        sa.CheckConstraint("reference_price > 0 AND fill_price > 0", name="fill_prices_positive"),
        sa.CheckConstraint("slippage >= 0", name="fill_slippage_non_negative"),
        sa.CheckConstraint(
            "cost_fixed >= 0 AND cost_per_share >= 0 AND cost_percentage >= 0 AND cost_total >= 0",
            name="fill_cost_non_negative",
        ),
        sa.CheckConstraint(
            "cost_total = cost_fixed + cost_per_share + cost_percentage",
            name="fill_cost_adds_up",
        ),
        sa.CheckConstraint("cash_after >= 0", name="fill_cash_non_negative"),
    )
    op.create_index("fill_order", "fill", ["portfolio_id", "order_id"])

    op.create_table(
        "trade_event",
        sa.Column("portfolio_id", sa.Uuid(), sa.ForeignKey("portfolio.id"), nullable=False),
        sa.Column("seq", sa.BigInteger(), nullable=False),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("prev_hash", sa.Text()),
        sa.Column("hash", sa.Text(), nullable=False),
        _now("recorded_at"),
        sa.PrimaryKeyConstraint("portfolio_id", "seq", "event_time"),
        sa.CheckConstraint("seq >= 1", name="trade_event_seq_positive"),
        sa.CheckConstraint(
            "type IN (" + ", ".join(f"'{name}'" for name in EVENT_TYPES) + ")",
            name="trade_event_type_valid",
        ),
        sa.CheckConstraint("version >= 1", name="trade_event_version_positive"),
        sa.CheckConstraint("jsonb_typeof(payload) = 'object'", name="trade_event_payload_object"),
        sa.CheckConstraint("char_length(hash) > 0", name="trade_event_hash_not_empty"),
        sa.CheckConstraint("seq = 1 OR prev_hash IS NOT NULL", name="trade_event_chained"),
    )

    op.create_table(
        "holding_history",
        sa.Column("portfolio_id", sa.Uuid(), sa.ForeignKey("portfolio.id"), nullable=False),
        sa.Column("seq", sa.BigInteger(), nullable=False),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("session", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.BigInteger(), nullable=False),
        sa.Column("cost_basis", CASH, nullable=False),
        sa.PrimaryKeyConstraint("portfolio_id", "seq", "symbol"),
        sa.CheckConstraint("seq >= 1 AND session >= 0", name="holding_history_position_valid"),
        sa.CheckConstraint("quantity >= 0", name="holding_history_quantity_non_negative"),
        sa.CheckConstraint("cost_basis >= 0", name="holding_history_cost_basis_non_negative"),
    )

    op.create_table(
        "portfolio_value",
        sa.Column("portfolio_id", sa.Uuid(), sa.ForeignKey("portfolio.id"), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("session", sa.Integer(), nullable=False),
        sa.Column("seq", sa.BigInteger(), nullable=False),
        sa.Column("cash", CASH, nullable=False),
        sa.Column("market_value", CASH, nullable=False),
        sa.Column("value", CASH, nullable=False),
        sa.Column("realised_pnl", CASH, nullable=False),
        sa.Column("unrealised_pnl", CASH, nullable=False),
        sa.Column("total_costs", CASH, nullable=False),
        sa.PrimaryKeyConstraint("portfolio_id", "ts"),
        sa.CheckConstraint("seq >= 1 AND session >= 0", name="portfolio_value_position_valid"),
        sa.CheckConstraint("cash >= 0", name="portfolio_value_cash_non_negative"),
        sa.CheckConstraint("market_value >= 0", name="portfolio_value_market_value_non_negative"),
        sa.CheckConstraint("total_costs >= 0", name="portfolio_value_costs_non_negative"),
    )

    op.create_table(
        "portfolio_metrics",
        sa.Column("run_id", sa.Uuid(), primary_key=True),
        sa.Column("portfolio_id", sa.Uuid(), sa.ForeignKey("portfolio.id"), nullable=False),
        sa.Column("final_seq", sa.BigInteger(), nullable=False),
        sa.Column("final_hash", sa.Text(), nullable=False),
        sa.Column("sessions", sa.Integer(), nullable=False),
        sa.Column("final_value", CASH, nullable=False),
        sa.Column("total_return", RATIO),
        sa.Column("volatility", RATIO),
        sa.Column("sharpe", RATIO),
        sa.Column("max_drawdown", RATIO),
        sa.Column("turnover", RATIO),
        sa.Column("trades", sa.Integer(), nullable=False),
        sa.Column("total_costs", CASH, nullable=False),
        _now("computed_at"),
        sa.CheckConstraint("final_seq >= 1 AND sessions >= 0", name="portfolio_metrics_run_valid"),
        sa.CheckConstraint(
            "volatility IS NULL OR volatility >= 0", name="portfolio_metrics_volatility"
        ),
        sa.CheckConstraint("turnover IS NULL OR turnover >= 0", name="portfolio_metrics_turnover"),
        sa.CheckConstraint("trades >= 0", name="portfolio_metrics_trades_non_negative"),
        sa.CheckConstraint("total_costs >= 0", name="portfolio_metrics_costs_non_negative"),
    )
    op.create_index("portfolio_metrics_portfolio", "portfolio_metrics", ["portfolio_id"])

    op.create_table(
        "portfolio_state_current",
        sa.Column("portfolio_id", sa.Uuid(), sa.ForeignKey("portfolio.id"), primary_key=True),
        sa.Column("last_seq", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("last_hash", sa.Text()),
        sa.Column("last_session", sa.Integer()),
        sa.Column("cash", CASH, nullable=False),
        _empty_object("positions"),
        _now("updated_at"),
        sa.CheckConstraint("last_seq >= 0", name="portfolio_state_current_seq_non_negative"),
        sa.CheckConstraint(
            "(last_seq = 0) = (last_hash IS NULL)", name="portfolio_state_current_hash_with_seq"
        ),
        sa.CheckConstraint("cash >= 0", name="portfolio_state_current_cash_non_negative"),
        sa.CheckConstraint(
            "jsonb_typeof(positions) = 'object'",
            name="portfolio_state_current_positions_object",
        ),
    )

    op.create_table(
        "instrument_ref",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("name", sa.Text()),
        sa.Column("sector", sa.Text()),
        sa.Column("exchange", sa.Text(), nullable=False),
        sa.Column("currency", sa.Text(), nullable=False),
        sa.Column("asset_class", sa.Text()),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'active'")),
        _now("updated_at"),
        sa.CheckConstraint("status IN ('active', 'retired')", name="instrument_ref_status_valid"),
    )
    op.create_index("instrument_ref_symbol", "instrument_ref", ["symbol"])

    # The log and the value series are time series. Their primary keys already index
    # (portfolio, ...), so no default time index.
    op.execute(
        "SELECT create_hypertable('trade_event', by_range('event_time', INTERVAL '1 year'),"
        " create_default_indexes => false)"
    )
    op.execute(
        "SELECT create_hypertable('portfolio_value', by_range('ts', INTERVAL '1 year'),"
        " create_default_indexes => false)"
    )

    for statement in GUARD_STATEMENTS:
        op.execute(statement)
    # Row triggers on a hypertable are copied to every chunk, present and future
    op.execute(
        "CREATE TRIGGER trade_event_seq_follows BEFORE INSERT ON trade_event"
        " FOR EACH ROW EXECUTE FUNCTION qs_trade_event_seq_follows()"
    )
    op.execute(
        "CREATE TRIGGER trade_event_append_only BEFORE UPDATE OR DELETE ON trade_event"
        " FOR EACH ROW EXECUTE FUNCTION qs_trading_append_only('trade_event')"
    )
    # Holdings are a projection: rows never change, but the rebuild may clear them
    op.execute(
        "CREATE TRIGGER holding_history_append_only BEFORE UPDATE ON holding_history"
        " FOR EACH ROW EXECUTE FUNCTION qs_trading_append_only('holding_history')"
    )
    # The migration runs as the service's own role, which owns the tables
    op.execute("REVOKE UPDATE, DELETE, TRUNCATE ON trade_event FROM PUBLIC, CURRENT_USER")
    op.execute("REVOKE UPDATE ON holding_history FROM PUBLIC, CURRENT_USER")


def downgrade() -> None:
    # Dropping a table drops its triggers and privileges with it
    for table in reversed(TABLES):
        op.drop_table(table)
    op.execute("DROP FUNCTION IF EXISTS qs_trade_event_seq_follows()")
    op.execute("DROP FUNCTION IF EXISTS qs_trading_append_only()")
