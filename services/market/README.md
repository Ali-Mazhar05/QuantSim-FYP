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

Settings: `QS_INGEST_POLL_SECONDS` (5), `QS_INGEST_BACKFILL_START` (2015-01-02), `QS_INGEST_OUTLIER_LOG_RETURN` (0.405), `QS_INGEST_OUTLIER_POLICY` (`flag` or `reject`), `QS_INGEST_CIRCUIT_FAILURES` (5). Migration `0002` adds `ingestion_run_item.report`.
## Ingestion run routes and scheduler

Routes under `/api/market`:

| Route | Roles |
|---|---|
| `POST /ingestion-runs` | admin (needs `trigger_ingestion` and `backfill_market_data`, which only the admin role holds) |
| `GET /ingestion-runs?status=&limit=`, `GET /ingestion-runs/{id}`, `GET /ingestion-runs/{id}/rejected?limit=&offset=` | admin, quant, analyst (`view_ingestion_runs`) |

- `POST` body: `mode` (`manual` or `backfill`), optional `start` and `end`, optional `instrument_ids` (all active instruments when absent), optional `idempotency_key`. It only queues the run and answers 202 with `{id, status, created}`; the worker executes it. The vendor is `QS_VENDOR` and `requested_by` is the admin's user id.
- 409 problem details carry `active_run_id` when an active run overlaps the same instruments and window. 422 for `start` after `end`, a backfill without `start`, an empty instrument list or unknown instrument ids (`unknown_instrument_ids`). A repeated `idempotency_key` answers 202 with the first run and `created: false`.
- The list is newest first (default 50, at most 200). The detail has the run, one item per instrument (counts, status, error, the gate's report) and the run report. `/rejected` lists the rejected bars with symbol, session date, every rule broken and the raw payload.

Scheduler, `python -m qs_market scheduler` (TEST only; design in `docs/ingestion-plan.md` sections 3.1 and 5.1):

| Setting | Default | Purpose |
|---|---|---|
| `QS_INGEST_SCHEDULER_ENABLED` | `false` | When false the command logs and idles, so a restart policy does not loop |
| `QS_INGEST_DAILY_TIME` | `22:30` | UTC, `HH:MM`, enqueues a `daily` run |
| `QS_INGEST_CATCHUP_TIME` | `09:30` | UTC, `HH:MM`, enqueues a `catchup` run (D16) |

- It only enqueues. The idempotency key is the mode and UTC date (`daily:2026-10-14`), so two schedulers, or a restart, create one run per mode and day.
- After downtime only the latest slot of each mode is enqueued, never a backlog; a run's window already reaches back five sessions.
- A slot blocked by a still active run for the same window is not marked handled and is retried on the next tick (every 30 seconds).
- `due_runs(now, last_enqueued, schedule)` is a pure function and is tested without sleeping.

## Instrument master

Routes, all under `/api/market`:

| Route | Roles |
|---|---|
| `GET /instruments?status=active\|retired`, `GET /instruments/{id}` | any signed-in role (`view_market_data`) |
| `POST /instruments`, `PATCH /instruments/{id}`, `POST /instruments/{id}/retire` | admin (`manage_instruments`) |

- The list returns what the POC Instruments page shows (`symbol`, `name`, `sector`, `price`, `change_pct`) plus `id`, `status`, `exchange` and `asset_class`. `price` is the latest stored close as an 8-decimal string and `change_pct` the percent change from the previous close with two decimals; each is `null` when the bars are missing (`change_pct` needs two bars).
- Adding an existing symbol and exchange, even a retired one, is a 409 naming the existing id and status. `PATCH` changes only name, sector and notes. Retiring keeps the row and its bars and is idempotent.
- Every write is audited with the acting user and request id and queues `instrument.created`, `instrument.annotated` or `instrument.retired` in the same transaction. A repeated retire queues nothing.
- With a symbol directory configured (next section), `POST /instruments` also checks the symbol against it. Without one, only the formats the database enforces are checked.

Seed the 40-instrument starting universe (30 equities, 10 ETFs; no network, safe to repeat):

```sh
python -m qs_market.seed
```

## Symbol directory

`qs_market/symbol_directory.py` reads the two public Nasdaq Trader files, `nasdaqlisted.txt` and `otherlisted.txt`, and `POST /instruments` uses them to refuse symbols that should not be added (FR-21).

- `QS_SYMBOL_DIRECTORY_DIR`: a folder holding both files. Unset (the default) disables the check, so DEV and tests that do not care add any symbol as before. Set to a folder that lacks a file, the service stops at start.
- `QS_SYMBOL_DIRECTORY_MAX_AGE_DAYS` (14): a directory whose file creation time is older logs a warning on use and still validates. Files are re-read when they change on disk, so a refresh needs no restart.
- Refused with 422 (`urn:quantsim:problem:validation`, field in `errors[].location`): a symbol not in the directory, a test issue, or a financial status other than normal (`symbol`); an ETF sent as `equity` or the reverse (`asset_class`). If the files disappear after start the add is a 503. The seed and `PATCH` are not checked.
- Class shares: `BRK.B` and `BRK-B` are one symbol; comparison upper-cases and turns `-` into `.`.
- Listing exchange is read from the directory (`N` XNYS, `A` XASE, `P` ARCX, `Z` BATS, `V` IEXG, `M` XCHI, everything in `nasdaqlisted.txt` XNAS) but not enforced: the seed universe lists its ETFs and WMT differently (see the test), and the listing exchange does not change the daily bars.
- Malformed rows are skipped and counted; a file with no header or no rows is an error.

Fetch a fresh copy by hand or from a scheduled job on the host (never in CI), then point the setting at the folder:

```sh
python scripts/fetch_symbol_directory.py --out /var/lib/quantsim/symdir
export QS_SYMBOL_DIRECTORY_DIR=/var/lib/quantsim/symdir
```

Tests use `tests/fixtures/symdir/`, the real lines of the 40 seed symbols and a few others (a test issue, a deficient status, a warrant, class shares) recorded from nasdaqtrader.com on 2026-10-14 with the real footer. No test reaches the network.

## Read API

One image (`ci/components.conf` component `market`) runs as five compose services in `deploy/compose/docker-compose.yml`:

| Service | Command | Where |
|---|---|---|
| `GET /instruments/{id}/bars?from&to&limit&cursor` | all signed-in | Clean bars with adjusted close, flags, revision and content hash |
| `GET /instruments/{id}/returns?from&to&limit&cursor` | all signed-in | Log return, adjusted log return, 20 and 60 session volatility |
| `GET /instruments/{id}/corporate-actions` | all signed-in | Splits and dividends |
| `GET /instruments/{id}/gaps?status=open\|resolved` | all signed-in | Sessions with no clean bar |
| `GET /instruments/{id}/quote` | all signed-in | Latest and previous close, change in percent, session date |
| `GET /data-quality` | admin, quant, analyst | One row per active instrument: last session, bar count, open gaps, flagged bars, rejected total, last run |

## Correlation matrices

`qs_market/correlation.py` (the maths, no database) and `qs_market/api_correlation.py`. `POST /api/market/correlations`, for every signed-in role, returns every window's matrix in one response (FR-MKT-004).

Body: a basket as `symbols` or `instrument_ids` (not both, 2 to 40), and either `windows` (explicit inclusive `start`/`end` dates, up to 250) or `rolling` (`length` and `step` in sessions plus an overall `start`/`end`; only whole windows). `min_observations` defaults to 20.

Rules:

- Pearson correlation of the stored adjusted log returns, so a split is not a crash.
- Sessions are the inner join of the basket inside the window: one `n_obs` per window, every cell uses the same sessions.
- Fewer than `min_observations` sessions makes every cell `null` with the reason `insufficient_observations`. A series that is constant in the window makes its row and column `null` with `constant_series`. Never NaN, never an error.
- The matrix is symmetric, the diagonal is exactly `"1.00000000"` when defined, values are strings with 8 decimals. Rows and columns are ordered by symbol.
- `fingerprint` is the sha256 of the sorted instrument ids, the window bounds, the method name and version, `min_observations`, and for every shared session the return value plus the content hashes of the bar it came from and the bar before it. The same inputs give the same fingerprint whatever the order of symbols or windows; a vendor correction of any bar used gives a new one. The exact encoding is in the module docstring.
- Problems: 404 for unknown symbols or ids (listed in `unknown`), 422 for an empty or single instrument basket, both or neither of symbols and ids, an inverted window, instruments with no returns in the range (listed in `instruments`), and requests beyond 40 instruments, 250 windows or the work cap.

```json
POST /api/market/correlations
{"symbols": ["AAPL", "MSFT"], "rolling": {"length": 60, "step": 20, "start": "2024-01-01", "end": "2024-12-31"}}

200
{"method": "pearson-adj-log-return", "method_version": 1, "min_observations": 20,
 "windows": [{"start": "2024-01-02", "end": "2024-03-27", "n_obs": 60,
              "fingerprint": "9c1f...e07a", "symbols": ["AAPL", "MSFT"],
              "matrix": [["1.00000000", "0.61234567"], ["0.61234567", "1.00000000"]],
              "unavailable": []}]}
```
