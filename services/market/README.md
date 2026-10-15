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
- Symbols are not checked against the Nasdaq directory yet; only the formats the database enforces.

Seed the 40-instrument starting universe (30 equities, 10 ETFs; no network, safe to repeat):

```sh
python -m qs_market.seed
```

## Read API

`qs_market/api_data.py`, under `/api/market`. Every number is a decimal string, never a float. Lists are ascending by session date and paged by keyset: pass the `next_cursor` of one page as `cursor` of the next (default `limit` 500, maximum 2000).

| Route | Roles | Returns |
|---|---|---|
| `GET /instruments/{id}/bars?from&to&limit&cursor` | all signed-in | Clean bars with adjusted close, flags, revision and content hash |
| `GET /instruments/{id}/candles?interval&from&to` | all signed-in | Chart series at a display interval (see below) |
| `GET /instruments/{id}/metrics?interval&from&to` | all signed-in | Period return, annualised volatility, maximum drawdown for that series |
| `GET /instruments/{id}/returns?from&to&limit&cursor` | all signed-in | Log return, adjusted log return, 20 and 60 session volatility |
| `GET /instruments/{id}/corporate-actions` | all signed-in | Splits and dividends |
| `GET /instruments/{id}/gaps?status=open\|resolved` | all signed-in | Sessions with no clean bar |
| `GET /instruments/{id}/quote` | all signed-in | Latest and previous close, change in percent, session date |
| `GET /data-quality` | admin, quant, analyst | One row per active instrument: last session, bar count, open gaps, flagged bars, rejected total, last run |

### Date range, intervals and metrics

**Date convention.** `from` and `to` are both inclusive session dates (`YYYY-MM-DD`). A reversed range, a malformed date or an interval other than `daily`, `weekly`, `monthly`, `yearly` answers 422; an unknown instrument 404. A valid range with no observations answers 200 with an empty list, never an invented series.

**Intervals.** Only daily bars are stored. `candles` derives the others on request from the bars inside the window: open is the first open, high the maximum high, low the minimum low, close the last close, volume the sum. A bucket is an ISO week (Monday to Sunday), a calendar month or a calendar year of the exchange's session date; only sessions that exist are aggregated, and the first and last bucket hold only the sessions inside the window. A candle is labelled by its last session (`session_date`) and also reports `period_start` and the number of `sessions` it summarises. The maths is in `series.py`.

**Metrics.** Computed from the candles of the requested interval, on the adjusted close when every candle has one (so a split is not a crash) and otherwise on the close; `price_basis` says which.

| Metric | Definition |
|---|---|
| `period_return` | last price / first price - 1 |
| `annualised_volatility` | sample standard deviation (n - 1) of the log returns, times the square root of the periods per year (252 daily, 52 weekly, 12 monthly, 1 yearly) |
| `max_drawdown` | the lowest of (price - running peak) / running peak; zero or negative; `drawdown_peak` and `drawdown_trough` give the dates |

A metric that cannot be computed is `null` and `unavailable` names it and the reason: fewer than two observations for all three, fewer than three for volatility, a zero first price for the return.

**Performance (NFR-PERF-01).** `tests/test_intervals_api.py` loads about 1,250 daily rows (five years) for one symbol and requires `bars`, daily and weekly `candles`, and `metrics` each to answer in under one second at the backend-query layer, excluding any vendor time. This is a measured target on the test database, not a production claim.
