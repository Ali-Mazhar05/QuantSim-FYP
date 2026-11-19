"""Tables of trading_db. Every change here needs a migration in ``migrations/versions``.

The append-only ``trade_event`` log is the source of truth; every other trading table is a
projection that the rebuild recreates from ``seq = 1``. Money follows NFR-INT-001: prices
are ``NUMERIC(20,8)``, cash and other amounts in cents are ``NUMERIC(20,2)``.

The CHECK constraints, the hypertables and the triggers that keep the log append-only and
gap-free live in the migrations; the definitions here mirror the columns, keys and indexes,
and a database test compares the two.
"""

from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    Numeric,
    PrimaryKeyConstraint,
    Table,
    Text,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

from qs_template.jobs import job_table
from qs_trading.domain.events import EventType

metadata = MetaData()

PRICE = Numeric(20, 8)
CASH = Numeric(20, 2)
# Metrics are small ratios; exact like every other stored number
RATIO = Numeric(20, 12)

EVENT_TYPES = tuple(member.value for member in EventType)


def _now(name: str) -> Column[Any]:
    return Column(name, DateTime(timezone=True), nullable=False, server_default=func.now())


def _empty_object(name: str) -> Column[Any]:
    return Column(name, JSONB, nullable=False, server_default=text("'{}'::jsonb"))


job = job_table(metadata)

strategy = Table(
    "strategy",
    metadata,
    Column("id", Uuid, primary_key=True, server_default=text("gen_random_uuid()")),
    Column("name", Text, nullable=False),
    Column("kind", Text, nullable=False),
    _empty_object("params"),
    Column("owner_id", Uuid, nullable=False),
    _now("created_at"),
    _now("updated_at"),
    CheckConstraint("char_length(name) BETWEEN 1 AND 120", name="strategy_name_length"),
    CheckConstraint("kind ~ '^[a-z][a-z0-9_]{0,39}$'", name="strategy_kind_format"),
    CheckConstraint("jsonb_typeof(params) = 'object'", name="strategy_params_object"),
)

portfolio = Table(
    "portfolio",
    metadata,
    Column("id", Uuid, primary_key=True, server_default=text("gen_random_uuid()")),
    Column("name", Text, nullable=False),
    Column("strategy_id", Uuid, ForeignKey("strategy.id"), nullable=False),
    Column("owner_id", Uuid, nullable=False),
    Column("initial_capital", CASH, nullable=False),
    Column("base_currency", Text, nullable=False, server_default=text("'USD'")),
    _empty_object("cost_model"),
    _empty_object("slippage_model"),
    Column("env_type", Text, nullable=False),
    Column("replay_environment_id", Uuid),
    Column("simulation_run_id", Uuid),
    Column("path_index", Integer),
    Column("source_fingerprint", Text),
    _now("created_at"),
    _now("updated_at"),
    CheckConstraint("char_length(name) BETWEEN 1 AND 120", name="portfolio_name_length"),
    CheckConstraint("initial_capital > 0", name="portfolio_capital_positive"),
    CheckConstraint("base_currency = 'USD'", name="portfolio_base_currency_usd"),
    CheckConstraint("env_type IN ('replay', 'simulation')", name="portfolio_env_type_valid"),
    CheckConstraint(
        "(env_type = 'replay' AND replay_environment_id IS NOT NULL"
        " AND simulation_run_id IS NULL AND path_index IS NULL)"
        " OR (env_type = 'simulation' AND simulation_run_id IS NOT NULL"
        " AND replay_environment_id IS NULL AND path_index IS NOT NULL)",
        name="portfolio_environment_binding",
    ),
    CheckConstraint("path_index IS NULL OR path_index >= 0", name="portfolio_path_index_valid"),
    CheckConstraint(
        "jsonb_typeof(cost_model) = 'object' AND jsonb_typeof(slippage_model) = 'object'",
        name="portfolio_models_are_objects",
    ),
    CheckConstraint(
        "source_fingerprint IS NULL OR char_length(source_fingerprint) > 0",
        name="portfolio_fingerprint_not_empty",
    ),
)

order = Table(
    "order",
    metadata,
    Column("portfolio_id", Uuid, ForeignKey("portfolio.id"), nullable=False),
    Column("order_id", Text, nullable=False),
    Column("symbol", Text, nullable=False),
    Column("side", Text, nullable=False),
    Column("quantity", BigInteger, nullable=False),
    Column("order_type", Text, nullable=False),
    Column("limit_price", PRICE),
    Column("placed_seq", BigInteger, nullable=False),
    Column("placed_session", Integer, nullable=False),
    Column("expires_session", Integer),
    Column("status", Text, nullable=False, server_default=text("'open'")),
    _now("updated_at"),
    PrimaryKeyConstraint("portfolio_id", "order_id"),
    CheckConstraint("side IN ('buy', 'sell')", name="order_side_valid"),
    CheckConstraint("quantity > 0", name="order_quantity_positive"),
    CheckConstraint("order_type IN ('market', 'limit')", name="order_type_valid"),
    CheckConstraint(
        "(order_type = 'limit') = (limit_price IS NOT NULL)", name="order_limit_price_iff_limit"
    ),
    CheckConstraint("limit_price IS NULL OR limit_price > 0", name="order_limit_price_positive"),
    CheckConstraint(
        "order_type = 'limit' OR expires_session IS NULL", name="order_market_never_expires"
    ),
    CheckConstraint(
        "status IN ('open', 'filled', 'rejected', 'expired')", name="order_status_valid"
    ),
    CheckConstraint("placed_seq >= 1 AND placed_session >= 0", name="order_placement_valid"),
)

fill = Table(
    "fill",
    metadata,
    Column("portfolio_id", Uuid, nullable=False),
    Column("seq", BigInteger, nullable=False),
    Column("order_id", Text, nullable=False),
    Column("session", Integer, nullable=False),
    Column("symbol", Text, nullable=False),
    Column("side", Text, nullable=False),
    Column("quantity", BigInteger, nullable=False),
    Column("reference_price", PRICE, nullable=False),
    Column("fill_price", PRICE, nullable=False),
    Column("slippage", PRICE, nullable=False),
    Column("cost_fixed", CASH, nullable=False),
    Column("cost_per_share", CASH, nullable=False),
    Column("cost_percentage", CASH, nullable=False),
    Column("cost_total", CASH, nullable=False),
    Column("cash_after", CASH, nullable=False),
    PrimaryKeyConstraint("portfolio_id", "seq"),
    ForeignKeyConstraint(
        ["portfolio_id", "order_id"],
        ["order.portfolio_id", "order.order_id"],
        name="fill_order_fk",
        ondelete="CASCADE",
    ),
    CheckConstraint("seq >= 1 AND session >= 0", name="fill_position_valid"),
    CheckConstraint("side IN ('buy', 'sell')", name="fill_side_valid"),
    CheckConstraint("quantity > 0", name="fill_quantity_positive"),
    CheckConstraint("reference_price > 0 AND fill_price > 0", name="fill_prices_positive"),
    CheckConstraint("slippage >= 0", name="fill_slippage_non_negative"),
    CheckConstraint(
        "cost_fixed >= 0 AND cost_per_share >= 0 AND cost_percentage >= 0 AND cost_total >= 0",
        name="fill_cost_non_negative",
    ),
    CheckConstraint(
        "cost_total = cost_fixed + cost_per_share + cost_percentage", name="fill_cost_adds_up"
    ),
    CheckConstraint("cash_after >= 0", name="fill_cash_non_negative"),
    Index("fill_order", "portfolio_id", "order_id"),
)

trade_event = Table(
    "trade_event",
    metadata,
    Column("portfolio_id", Uuid, ForeignKey("portfolio.id"), nullable=False),
    Column("seq", BigInteger, nullable=False),
    Column("event_time", DateTime(timezone=True), nullable=False),
    Column("type", Text, nullable=False),
    Column("version", Integer, nullable=False, server_default=text("1")),
    Column("payload", JSONB, nullable=False),
    Column("prev_hash", Text),
    Column("hash", Text, nullable=False),
    _now("recorded_at"),
    PrimaryKeyConstraint("portfolio_id", "seq", "event_time"),
    CheckConstraint("seq >= 1", name="trade_event_seq_positive"),
    CheckConstraint(
        "type IN (" + ", ".join(f"'{name}'" for name in EVENT_TYPES) + ")",
        name="trade_event_type_valid",
    ),
    CheckConstraint("version >= 1", name="trade_event_version_positive"),
    CheckConstraint("jsonb_typeof(payload) = 'object'", name="trade_event_payload_object"),
    CheckConstraint("char_length(hash) > 0", name="trade_event_hash_not_empty"),
    CheckConstraint("seq = 1 OR prev_hash IS NOT NULL", name="trade_event_chained"),
)

holding_history = Table(
    "holding_history",
    metadata,
    Column("portfolio_id", Uuid, ForeignKey("portfolio.id"), nullable=False),
    Column("seq", BigInteger, nullable=False),
    Column("symbol", Text, nullable=False),
    Column("session", Integer, nullable=False),
    Column("quantity", BigInteger, nullable=False),
    Column("cost_basis", CASH, nullable=False),
    PrimaryKeyConstraint("portfolio_id", "seq", "symbol"),
    CheckConstraint("seq >= 1 AND session >= 0", name="holding_history_position_valid"),
    CheckConstraint("quantity >= 0", name="holding_history_quantity_non_negative"),
    CheckConstraint("cost_basis >= 0", name="holding_history_cost_basis_non_negative"),
)

portfolio_value = Table(
    "portfolio_value",
    metadata,
    Column("portfolio_id", Uuid, ForeignKey("portfolio.id"), nullable=False),
    Column("ts", DateTime(timezone=True), nullable=False),
    Column("session", Integer, nullable=False),
    Column("seq", BigInteger, nullable=False),
    Column("cash", CASH, nullable=False),
    Column("market_value", CASH, nullable=False),
    Column("value", CASH, nullable=False),
    Column("realised_pnl", CASH, nullable=False),
    Column("unrealised_pnl", CASH, nullable=False),
    Column("total_costs", CASH, nullable=False),
    PrimaryKeyConstraint("portfolio_id", "ts"),
    CheckConstraint("seq >= 1 AND session >= 0", name="portfolio_value_position_valid"),
    CheckConstraint("cash >= 0", name="portfolio_value_cash_non_negative"),
    CheckConstraint("market_value >= 0", name="portfolio_value_market_value_non_negative"),
    CheckConstraint("total_costs >= 0", name="portfolio_value_costs_non_negative"),
)

portfolio_metrics = Table(
    "portfolio_metrics",
    metadata,
    Column("run_id", Uuid, primary_key=True),
    Column("portfolio_id", Uuid, ForeignKey("portfolio.id"), nullable=False),
    Column("final_seq", BigInteger, nullable=False),
    Column("final_hash", Text, nullable=False),
    Column("sessions", Integer, nullable=False),
    Column("final_value", CASH, nullable=False),
    Column("total_return", RATIO),
    Column("volatility", RATIO),
    Column("sharpe", RATIO),
    Column("max_drawdown", RATIO),
    Column("turnover", RATIO),
    Column("trades", Integer, nullable=False),
    Column("total_costs", CASH, nullable=False),
    _now("computed_at"),
    CheckConstraint("final_seq >= 1 AND sessions >= 0", name="portfolio_metrics_run_valid"),
    CheckConstraint("volatility IS NULL OR volatility >= 0", name="portfolio_metrics_volatility"),
    CheckConstraint("turnover IS NULL OR turnover >= 0", name="portfolio_metrics_turnover"),
    CheckConstraint("trades >= 0", name="portfolio_metrics_trades_non_negative"),
    CheckConstraint("total_costs >= 0", name="portfolio_metrics_costs_non_negative"),
    Index("portfolio_metrics_portfolio", "portfolio_id"),
)

portfolio_state_current = Table(
    "portfolio_state_current",
    metadata,
    Column("portfolio_id", Uuid, ForeignKey("portfolio.id"), primary_key=True),
    Column("last_seq", BigInteger, nullable=False, server_default=text("0")),
    Column("last_hash", Text),
    Column("last_session", Integer),
    Column("cash", CASH, nullable=False),
    _empty_object("positions"),
    _now("updated_at"),
    CheckConstraint("last_seq >= 0", name="portfolio_state_current_seq_non_negative"),
    CheckConstraint(
        "(last_seq = 0) = (last_hash IS NULL)", name="portfolio_state_current_hash_with_seq"
    ),
    CheckConstraint("cash >= 0", name="portfolio_state_current_cash_non_negative"),
    CheckConstraint(
        "jsonb_typeof(positions) = 'object'", name="portfolio_state_current_positions_object"
    ),
)

instrument_ref = Table(
    "instrument_ref",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("symbol", Text, nullable=False),
    Column("name", Text),
    Column("sector", Text),
    Column("exchange", Text, nullable=False),
    Column("currency", Text, nullable=False),
    Column("asset_class", Text),
    Column("status", Text, nullable=False, server_default=text("'active'")),
    _now("updated_at"),
    CheckConstraint("status IN ('active', 'retired')", name="instrument_ref_status_valid"),
    Index("instrument_ref_symbol", "symbol"),
)
