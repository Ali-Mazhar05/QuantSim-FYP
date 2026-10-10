# Market Data service (M1)

Owns `market_db`. In Iteration 1 it holds the instrument master and ingests end-of-day prices. Every vendor record passes a cleaning gate before it is published. The service records what was passed, corrected and rejected, then computes returns and volatility and publishes events. The requirements are FR-20 to FR-31 in `docs/bmad/planning-artifacts/prds/prd-QuantSim-2026-10-10/prd.md`; the design is in `docs/ingestion-plan.md`.

## Schema

`models.py` defines the tables and `migrations/` creates them. A test checks that the two match exactly.

| Table | Purpose |
|---|---|
| `instrument` | Instrument master (audited). Retiring is non-destructive |
| `ingestion_run`, `ingestion_run_item` | One row per run and per instrument in the run. The database refuses an item whose counts do not add up |
| `staging_bar` | Raw vendor records, kept for 90 days |
| `bar` (hypertable) | Published clean bars. Prices are `NUMERIC(23,8)`. The database refuses non-positive prices, `low > high`, open or close outside the range, and negative volume |
| `bar_revision` | Previous values of corrected bars |
| `rejected_bar` | Records the cleaning gate refused, with every rule they broke |
| `data_gap` | Expected sessions with no clean bar |
| `corporate_action` | Splits and cash dividends |
| `return_series` (hypertable) | Log returns, adjusted log returns, and 20- and 60-session volatility |
| `replay_session` | Replay windows. The database refuses `end_time <= start_time` |
| `outbox`, `processed_events`, `audit_log` | From the service template |

## Migrations

Schema changes follow the migration protocol (`docs/ingestion-plan.md` §4.2):
- Add a new numbered revision; never edit an applied one.
- Every revision must have a working downgrade.
- Before pushing, run:

  ```sh
  ci/scripts/migration-check.sh market
  ```

The TimescaleDB extension is created by `db-init` in deployed environments; the first migration only creates it when it is missing (as in CI, where the database user is a superuser).

## Tests

Run these from the repository root:

```sh
ci/scripts/python-ci.sh services/market      # ruff, mypy, pytest with a throwaway database
ci/scripts/migration-check.sh market         # upgrade, downgrade, upgrade on an empty database
```
