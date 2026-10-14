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

## Real-data validation

Unit tests prove each rule on constructed bars. `tests/realdata/` proves the code on years
of real vendor bars, and is skipped when no corpus is present, so CI and fresh clones are
unaffected.

| File | What it checks |
|---|---|
| `test_gate_on_real_data.py` | Vendor rows match the exchange calendar exactly; real history passes with no rejects or gaps; real splits (NVDA, TSLA, AAPL) are read correctly and never flagged; dividends survive; the result is deterministic and independent of input order |
| `test_returns_on_real_data.py` | Log returns and 20 and 60 session volatility equal independent numpy and pandas computations; a split does not look like a crash in adjusted returns |
| `test_faults_in_real_data.py` | Each of eight planted faults in real AAPL bars is caught by its own rule and no untouched bar changes |
| `test_performance_on_real_data.py` | Time and memory budgets for the planned 40 instrument, 11 year backfill |

Record the corpus once (six symbols, 2015 to today, six requests) and run the suite:

```sh
TIINGO_API_KEY=... uv run python scripts/fetch_realdata.py
uv run python -m pytest tests/realdata -q
```

The corpus goes to `tests/realdata/corpus/`, which git ignores: the free tier is for
personal use, so the data is fetched on demand and never committed. Point
`QS_REALDATA_DIR` at another folder to keep it elsewhere. Budgets can be loosened with
`QS_REALDATA_GATE_SECONDS`, `QS_REALDATA_RETURNS_SECONDS` and `QS_REALDATA_MEMORY_MB`.

## Ingestion pipeline

`qs_market.pipeline` executes ingestion runs (design: `docs/ingestion-plan.md` section 5).

- **Queue** (`runs.py`): a run is an `ingestion_run` row. A scheduled mode uses one idempotency key per day, so two schedulers create one run; a second run for the same instruments and window while one is active is refused with the active run id (`RunConflict`). One worker executes at a time, enforced by a PostgreSQL advisory lock held on its own connection. A run left `running` by a dead worker is reset to `pending` by the next worker and repeated; instruments that already committed are skipped.
- **Per instrument, one transaction** (`runner.py`): fetch, stage in `staging_bar`, clean through the gate, publish (new session inserted, same raw hash left alone, changed raw hash becomes a revision with the old values in `bar_revision` and a `bar.corrected` event), record rejected bars, gaps and corporate actions, recompute returns from the earliest changed session, and queue `bar.ingested`. A failure rolls back the bars and the events together. Restated adjusted prices refresh the stored values without a revision.
- **Run statuses**: `succeeded` (every instrument succeeded or had no data), `partially_succeeded` (some failed or were deferred; five consecutive transient vendor failures open the circuit and defer the rest; an exhausted request budget defers the rest), `failed` (the vendor refused the key, recorded as `vendor_auth`, or nothing succeeded). Item statuses are `succeeded`, `no_data`, `deferred` and `failed`.
- **Commands**: `python -m qs_market worker | relay | run-once`.

Try it with the recorded fixtures (no network):

```sh
export QS_DATABASE_URL=postgresql+asyncpg://... QS_REDIS_URL=redis://localhost QS_VENDOR=fixture \
  QS_FIXTURE_DIR=services/market/tests/fixtures
python -m qs_market run-once --mode manual --start 2024-01-02 --end 2024-02-13 --symbol AAPL
```

Settings: `QS_INGEST_POLL_SECONDS` (5), `QS_INGEST_BACKFILL_START` (2015-01-02), `QS_INGEST_OUTLIER_LOG_RETURN` (0.405), `QS_INGEST_OUTLIER_POLICY` (`flag` or `reject`), `QS_INGEST_CIRCUIT_FAILURES` (5). Migration `0002` adds `ingestion_run_item.report`.
## Instrument master

Routes, all under `/api/market`:

| Route | Roles |
|---|---|
| `GET /instruments?status=active\|retired`, `GET /instruments/{id}` | any signed-in role (`view_market_data`) |
| `POST /instruments`, `PATCH /instruments/{id}`, `POST /instruments/{id}/retire` | admin (`manage_instruments`) |

- The list returns what the POC Instruments page shows (`symbol`, `name`, `sector`, `price`, `change_pct`) plus `id`, `status`, `exchange` and `asset_class`. `price` is the latest stored close as an 8-decimal string and `change_pct` the percent change from the previous close with two decimals; each is `null` when the bars are missing (`change_pct` needs two bars).
- Adding an existing symbol and exchange, even a retired one, is a 409 naming the existing id and status. `PATCH` changes only name, sector and notes. Retiring keeps the row and its bars and is idempotent.
- Every write is audited with the acting user and request id and queues `instrument.created`, `instrument.annotated` or `instrument.retired` in the same transaction. A repeated retire queues nothing.
- Symbols are not checked against the Nasdaq directory yet; only the formats the database enforces.

Seed the 40-instrument starting universe (30 equities, 10 ETFs; no network, safe to repeat):

```sh
python -m qs_market.seed
```

## Deployment

One image (`ci/components.conf` component `market`) runs as five compose services in `deploy/compose/docker-compose.yml`:

| Service | Command | Where |
|---|---|---|
| `market` | `uvicorn qs_market.main:create --factory` (image default), routed by the gateway at `/api/market` | every environment |
| `market-worker` | `python -m qs_market worker` | every environment |
| `market-relay` | `python -m qs_market relay` | every environment |
| `market-scheduler` | `python -m qs_market scheduler` | only where `QS_INGEST_SCHEDULER_ENABLED=true` (TEST); `deploy.sh` enables the `scheduler` profile from that setting |
| `market-migrate` | `alembic upgrade head`, one shot before the new version starts | every deploy |

`db-init` creates the `market` database, the `market` role and the TimescaleDB extension (idempotent).

Settings come from `deploy/env/<env>.env` (not secret: `MARKET_VENDOR`, `TIINGO_REQUESTS_PER_HOUR`, `TIINGO_SCHEDULED_RESERVE`, `INGEST_BACKFILL_START`, `INGEST_OUTLIER_LOG_RETURN`, `INGEST_OUTLIER_POLICY`, `QS_INGEST_SCHEDULER_ENABLED`) and from the encrypted `deploy/secrets/<env>.enc.env` (secret: `TIINGO_API_KEY`, `MARKET_DB_PASSWORD`). DEV uses the `fixture` vendor; TEST, ACC and PROD use `tiingo` and share one key's budget, so only TEST runs the scheduler.

`ci/scripts/smoke-market.sh` (called by `smoke.sh`) checks `/api/market/ready`; where the vendor is `fixture` it also seeds the instruments and does one manual run of AAPL over the recorded window and checks the run report. Set `SMOKE_ADMIN_USER` and `SMOKE_ADMIN_PASSWORD` to make that run go through the API instead of the container.

## Runbook

Run these against the environment's API (`<api>` is the address in the website's `config.json`; `$TOKEN` is an admin access token from `POST /api/platform/auth/login`). Only one run per instruments and window can be active; a second request answers 409 with the active run id.

**Re-run a window** (the vendor restated prices, or a run failed):

```sh
curl -X POST "<api>/api/market/ingestion-runs" -H "Authorization: Bearer $TOKEN"   -H "Content-Type: application/json"   -d '{"mode":"manual","start":"2024-03-01","end":"2024-03-15"}'
```

Add `"symbols":["AAPL"]` to limit it. The call answers 202 with the run id at once; the worker executes it. Re-running is safe: unchanged bars are left alone and changed bars become revisions.

**Backfill an instrument** (a newly added symbol): the same call with `"mode":"backfill"`, `"symbols":["XYZ"]` and an optional `"start"` (default `QS_INGEST_BACKFILL_START`). A backfill may not use the budget reserved for scheduled runs, so a long history can take several hours on the free tier; the run ends `partially_succeeded` with deferred instruments when the budget runs out, and repeating the call resumes it.

**Retire a delisted symbol**: `POST <api>/api/market/instruments/{id}/retire`. Bars are kept; the scheduler stops fetching it. Retiring twice is harmless.

**Read a run report**: `GET <api>/api/market/ingestion-runs/{id}` gives the status, the per-instrument items and the report (counts of received, passed, corrected, rejected, new and revised bars, and rejections by rule). `GET .../ingestion-runs/{id}/rejected` lists the rejected bars with the rules they broke. `failed` with `vendor_auth` means the key was refused (see below). Without a token, from the host: `docker exec <project>-market-1 python -m qs_market run-once --mode manual --symbol AAPL --start 2024-01-02 --end 2024-02-13` runs and prints a report.

**Rotate the Tiingo key**:
1. Create the new key at tiingo.com and check it with `TIINGO_API_KEY=<new> python services/market/scripts/vendor_check.py AAPL` (two requests at most).
2. `ci/scripts/set-secret.sh TIINGO_API_KEY all`, then merge the changed `deploy/secrets/*.enc.env` files through a pull request.
3. The next deploy of each environment restarts the worker with the new key. The hourly budget is counted in Redis per key (a hash of it), so the new key starts with a fresh count; avoid heavy runs in the first hour after rotating.
4. Revoke the old key at Tiingo and trigger a manual run on TEST to confirm.
