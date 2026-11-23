# simulation_db: entity-relationship diagram

Database of the Simulation service (M2), PostgreSQL 17.

**Generated, do not edit by hand.** Run `uv run python scripts/erd.py` in
`services/simulation` after any schema change; `tests/test_erd.py` fails while this file is
out of date. The source is the table definitions in
`services/simulation/src/qs_simulation/models.py` (checked against the migrations by
`tests/test_schema.py`) plus the job queue, outbox, processed-events and audit tables from
`libs/qs_template`.

How to read it:
- `PK` primary key, `FK` foreign key, `UK` unique. `"23,10"` is the numeric precision and
  scale: prices are exact decimals with 10 places, never floating point.
- `"optional"` columns may be empty; every other column is required.
- Solid lines are foreign keys. Dotted lines are references the schema deliberately does
  not enforce with a foreign key: `instrument_ref` is a cache of the market service's
  instruments for display, so nothing points at it by constraint.
- `run_instrument` points at `calibration (id, instrument_id)`, so a run cannot use another
  instrument's calibration, even through raw SQL.
- `path_value` holds every path of a small run; a larger run keeps its seed and
  `path_quantile` and regenerates a path on demand (ADR 03).

```mermaid
---
title: simulation_db
---
erDiagram
    calibration ||--o{ run_instrument : "calibration_id"
    calibration ||--o{ run_instrument : "instrument_id"
    instrument_ref ||..o{ calibration : "instrument_id"
    instrument_ref ||..o{ run_instrument : "instrument_id"
    job |o--o{ run : "job_id"
    run |o--o{ run : "parent_run_id"
    run ||--o{ run_correlation : "run_id"
    run ||--o{ run_instrument : "run_id"
    run_instrument ||--o{ path_quantile : "instrument_id"
    run_instrument ||--o{ path_quantile : "run_id"
    run_instrument ||--o{ path_value : "instrument_id"
    run_instrument ||--o{ path_value : "run_id"
    run_instrument ||--o{ run_statistics : "instrument_id"
    run_instrument ||--o{ run_statistics : "run_id"
    scenario |o--o{ run : "scenario_id"
    audit_log {
        bigint id PK
        text table_name
        text operation
        text row_id
        jsonb old_data "optional"
        jsonb new_data "optional"
        text changed_by "optional"
        text request_id "optional"
        timestamptz changed_at
        bigint txid
    }
    calibration {
        uuid id PK
        text model
        uuid instrument_id
        date window_start
        date window_end
        jsonb params
        jsonb std_errors
        numeric log_likelihood "28,12"
        numeric aic "28,12"
        int n_obs
        bool converged
        text input_fingerprint
        text qs_quant_version
        uuid created_by
        timestamptz created_at
    }
    instrument_ref {
        uuid instrument_id PK
        text symbol
        text name
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
    path_quantile {
        uuid run_id PK, FK
        uuid instrument_id PK, FK
        int step PK
        numeric q01 "23,10"
        numeric q05 "23,10"
        numeric q25 "23,10"
        numeric q50 "23,10"
        numeric q75 "23,10"
        numeric q95 "23,10"
        numeric q99 "23,10"
    }
    path_value {
        uuid run_id PK, FK
        uuid instrument_id PK, FK
        int path_index PK
        int step PK
        numeric price "23,10"
    }
    processed_events {
        text consumer_group PK
        uuid event_id PK
        text event_type
        timestamptz processed_at
    }
    run {
        uuid id PK
        text model
        int n_paths
        int n_steps
        bigint seed
        text idempotency_key UK
        text status
        text storage_mode
        uuid parent_run_id FK "optional"
        uuid scenario_id FK "optional"
        uuid job_id FK "optional"
        int median_path_index "optional"
        text error "optional"
        uuid created_by
        timestamptz created_at
        timestamptz started_at "optional"
        timestamptz finished_at "optional"
    }
    run_correlation {
        uuid run_id PK, FK
        int size
        jsonb matrix
        bool repair_applied
        numeric min_eigenvalue_before "28,12"
        numeric frobenius_change "28,12"
    }
    run_instrument {
        uuid run_id PK, FK
        uuid instrument_id PK, FK
        uuid calibration_id FK
        int position
        numeric s0 "23,10"
    }
    run_statistics {
        uuid run_id PK, FK
        uuid instrument_id PK, FK
        numeric mean_price "23,10"
        numeric median_price "23,10"
        numeric p5_price "23,10"
        numeric p95_price "23,10"
        numeric var95 "28,12"
        numeric cvar95 "28,12"
    }
    scenario {
        uuid id PK
        text code UK
        text name
        text type
        jsonb params
        timestamptz created_at
    }
```
