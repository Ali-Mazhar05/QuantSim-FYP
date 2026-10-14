# Market Data service (M1)

Owns `market_db`. In Iteration 1 it holds the instrument master and ingests end-of-day prices. Every vendor record passes a cleaning gate before it is published. The service records what was passed, corrected and rejected, then computes returns and volatility and publishes events. The requirements are FR-20 to FR-31 in `docs/bmad/planning-artifacts/prds/prd-QuantSim-2026-10-10/prd.md`; the design is in `docs/ingestion-plan.md`.

## Schema

`models.py` defines the tables and `migrations/` creates them. A test checks that the two match exactly.

| Table | Purpose |
|---|---|
| `instrument` | Instrument master (audited), with the sector the POC Instruments page shows. Retiring is non-destructive |
| `ingestion_run`, `ingestion_run_item` | One row per run and per instrument in the run. The database refuses an item whose counts do not add up |
| `staging_bar` | Raw vendor records, kept for 90 days |
| `bar` (hypertable) | Published clean bars. Prices are `NUMERIC(23,8)` and adjusted prices `NUMERIC(23,10)`, the precision the vendor sends. The database refuses non-positive prices, `low > high`, open or close outside the range, and negative volume |
| `bar_revision` | Previous values of corrected bars |
| `rejected_bar` | Records the cleaning gate refused, with every rule they broke |
| `data_gap` | Expected sessions with no clean bar |
| `corporate_action` | Splits and cash dividends |
| `return_series` (hypertable) | Log returns, adjusted log returns, and 20- and 60-session volatility, as exact `NUMERIC(20,12)` |
| `market_environment` | Market environments shaped like the POC pages (type, universe, instruments, window, frequency, status). This is also the replay window: the database refuses `end_date <= start_date` (NFR-INT-003) and values the POC does not have. Play, pause and speed arrive with Iteration 2 |
| `outbox`, `processed_events`, `audit_log` | From the service template |

## Migrations

Schema changes follow the migration protocol (`docs/ingestion-plan.md` §4.2):
- Add a new numbered revision; never edit an applied one.
- Every revision must have a working downgrade.
- Before pushing, run:

  ```sh
  ci/scripts/migration-check.sh market
  ```

The TimescaleDB extension needs a superuser, so it is not created by a migration: `db-init` creates it in deployed environments, and the test fixtures create it in CI. The migrations run as the service's own role and only create the hypertables.

## Tests

Run these from the repository root:

```sh
ci/scripts/python-ci.sh services/market      # ruff, mypy, pytest with a throwaway database
ci/scripts/migration-check.sh market         # upgrade, downgrade, upgrade on an empty database
```

## Vendor adapter

`qs_market.vendor` fetches end-of-day prices behind one `PriceSource` interface and hands the cleaning gate records in its own shape (snake_case keys, `Decimal` values, `YYYY-MM-DD` dates). The vendor is chosen by configuration:

| Setting | Default | Purpose |
|---|---|---|
| `QS_VENDOR` | `fixture` | `tiingo` or `fixture` (recorded responses, no network) |
| `QS_FIXTURE_DIR` | none | Directory of `{SYMBOL}.json` for the fixture vendor |
| `QS_TIINGO_API_KEY` | none | Required when the vendor is `tiingo`; the service refuses to start without it |
| `QS_TIINGO_BASE_URL` | `https://api.tiingo.com` | |
| `QS_TIINGO_REQUESTS_PER_HOUR` | `45` | Shared hourly budget for the key, counted in Redis |
| `QS_TIINGO_SCHEDULED_RESERVE` | `40` | Requests per hour a backfill or manual run may not use |
| `QS_TIINGO_TIMEOUT_SECONDS` | `30` | Per request |

Behaviour to know when operating it:
- Timeouts, 5xx and 429 are retried up to 4 attempts in total with exponential backoff and jitter; a `Retry-After` header is honoured. 404 (unknown symbol), 401 and 403 are never retried.
- Tiingo sends no rate-limit headers, so every request, retries included, is counted against the hourly budget. An empty budget defers the work (`BudgetExhausted`) rather than waiting. If Redis is unreachable the call is refused, never made unmetered.
- Tests never contact `api.tiingo.com`; a test-suite guard fails any test that tries.
- To check the real vendor by hand, with one symbol and at most two requests:

  ```sh
  TIINGO_API_KEY=... python services/market/scripts/vendor_check.py AAPL
  ```
