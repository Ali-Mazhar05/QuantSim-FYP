# trading_db: entity-relationship diagram

Database of the Trading service (Lane A), PostgreSQL 17 with TimescaleDB.

**Generated, do not edit by hand.** Run `uv run python scripts/erd.py` in
`services/trading` after any schema change; `tests/test_erd.py` fails while this file is
out of date. The source is the table definitions in
`services/trading/src/qs_trading/models.py` (checked against the migrations by the trading
schema tests) plus the job queue, outbox and processed-events tables from `libs/qs_template`.

How to read it:
- `PK` primary key, `FK` foreign key, `UK` unique. `"23,10"` is the numeric precision and
  scale: money and quantities are exact decimals, never floating point.
- `"optional"` columns may be empty; every other column is required.
- `trade_event` is the hash-chained event log of a run; holdings, values, metrics and the
  current state are projections rebuilt from it.
- `instrument_ref` is a cache of the market service's instruments, used for display.

```mermaid
---
title: trading_db
---
erDiagram
    order ||--o{ fill : "order_id"
    order ||--o{ fill : "portfolio_id"
    portfolio ||--o{ holding_history : "portfolio_id"
    portfolio ||--o{ order : "portfolio_id"
    portfolio ||--o{ portfolio_metrics : "portfolio_id"
    portfolio ||--o{ portfolio_state_current : "portfolio_id"
    portfolio ||--o{ portfolio_value : "portfolio_id"
    portfolio ||--o{ trade_event : "portfolio_id"
    strategy ||--o{ portfolio : "strategy_id"
    fill {
        uuid portfolio_id PK, FK
        bigint seq PK
        text order_id FK
        int session
        text symbol
        text side
        bigint quantity
        numeric reference_price "20,8"
        numeric fill_price "20,8"
        numeric slippage "20,8"
        numeric cost_fixed "20,2"
        numeric cost_per_share "20,2"
        numeric cost_percentage "20,2"
        numeric cost_total "20,2"
        numeric cash_after "20,2"
    }
    holding_history {
        uuid portfolio_id PK, FK
        bigint seq PK
        text symbol PK
        int session
        bigint quantity
        numeric cost_basis "20,2"
    }
    instrument_ref {
        uuid id PK
        text symbol
        text name "optional"
        text sector "optional"
        text exchange
        text currency
        text asset_class "optional"
        text status
        timestamptz updated_at
    }
    job {
        uuid id PK
        text kind
        text idempotency_key UK
        jsonb payload
        text status
        float8 progress
        int attempts
        int max_attempts
        text lease_owner "optional"
        timestamptz lease_expires_at "optional"
        jsonb result "optional"
        text error "optional"
        timestamptz created_at
        timestamptz started_at "optional"
        timestamptz finished_at "optional"
        timestamptz updated_at
    }
    order {
        uuid portfolio_id PK, FK
        text order_id PK
        text symbol
        text side
        bigint quantity
        text order_type
        numeric limit_price "20,8; optional"
        bigint placed_seq
        int placed_session
        int expires_session "optional"
        text status
        timestamptz updated_at
    }
    outbox {
        bigint id PK
        uuid event_id UK
        text topic
        text message_key
        text event_type
        jsonb payload
        timestamptz created_at
        timestamptz published_at "optional"
        int attempts
        text last_error "optional"
    }
    portfolio {
        uuid id PK
        text name
        uuid strategy_id FK
        uuid owner_id
        numeric initial_capital "20,2"
        text base_currency
        jsonb cost_model
        jsonb slippage_model
        text env_type
        uuid replay_environment_id "optional"
        uuid simulation_run_id "optional"
        int path_index "optional"
        text source_fingerprint "optional"
        timestamptz created_at
        timestamptz updated_at
    }
    portfolio_metrics {
        uuid run_id PK
        uuid portfolio_id FK
        bigint final_seq
        text final_hash
        int sessions
        numeric final_value "20,2"
        numeric total_return "20,12; optional"
        numeric volatility "20,12; optional"
        numeric sharpe "20,12; optional"
        numeric max_drawdown "20,12; optional"
        numeric turnover "20,12; optional"
        int trades
        numeric total_costs "20,2"
        timestamptz computed_at
    }
    portfolio_state_current {
        uuid portfolio_id PK, FK
        bigint last_seq
        text last_hash "optional"
        int last_session "optional"
        numeric cash "20,2"
        jsonb positions
        timestamptz updated_at
    }
    portfolio_value {
        uuid portfolio_id PK, FK
        timestamptz ts PK
        int session
        bigint seq
        numeric cash "20,2"
        numeric market_value "20,2"
        numeric value "20,2"
        numeric realised_pnl "20,2"
        numeric unrealised_pnl "20,2"
        numeric total_costs "20,2"
    }
    processed_events {
        text consumer_group PK
        uuid event_id PK
        text event_type
        timestamptz processed_at
    }
    strategy {
        uuid id PK
        text name
        text kind
        jsonb params
        uuid owner_id
        timestamptz created_at
        timestamptz updated_at
    }
    trade_event {
        uuid portfolio_id PK, FK
        bigint seq PK
        timestamptz event_time PK
        text type
        int version
        jsonb payload
        text prev_hash "optional"
        text hash
        timestamptz recorded_at
    }
```
