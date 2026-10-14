# Ingestion Engine Plan (M1 Market Data)

The detailed plan for building QuantSim's market-data ingestion engine: what it must do,
what it builds on, how it is designed, how it is tested and deployed, and the order of
work. Implementation starts once the CI/CD server is running; this plan is prepared in
parallel so work can begin immediately after.

Task ids (I1-xx) refer to [iteration-plan.md](iteration-plan.md).

---

## 1. Scope

### In scope for Iteration 1
| Requirement | What the engine does |
|---|---|
| FR-MKT-001 | Instrument master: admins add, annotate and retire instruments (retire is non-destructive) |
| FR-MKT-002 | Scheduled ingestion of daily OHLCV bars for every active instrument; each run records status, counts and errors; re-running a window never duplicates rows |
| FR-MKT-011 | Cleaning gate before publication: missing, duplicate, non-positive and out-of-range bars, zero volume; timestamps aligned to UTC on the exchange calendar; a report of what was corrected, rejected and passed untouched |
| FR-MKT-003 | Returns and volatility computed once, stored and published |
| FR-MKT-010 (Extended, cheap now) | Splits and dividends recorded from the vendor's data; raw and adjusted series both kept |
| FR-MKT-007 (create only), FR-MKT-008, FR-MKT-009 | Replay-session creation with the window rule enforced in the API and the database; the shared tick-event contract. Playback itself is Iteration 2 |
| NFR-INT-001 | Prices stored as fixed-precision decimals |
| NFR-REL-005, -007, -008 | Re-runnable jobs, outbox events, idempotent effects |
| NFR-PERF-004, -005 | Trigger acknowledged within 800 ms; every vendor call bounded by a timeout |
| NFR-OBS-002, -003 | Structured logs and metrics per run and per vendor call; outbox backlog visible |

### Later (designed for, not built now)
| Item | When |
|---|---|
| Correlation matrices (FR-MKT-004, I1-29) | End of Iteration 1 if time allows, otherwise Iteration 3 with TDA |
| News ingestion (FR-MKT-006) | Iteration 2 |
| Replay playback and tick streaming (FR-MKT-007) | Iteration 2 |
| Second vendor for cross-checking outliers | When a second free source is chosen |

---

## 2. Investigation findings

### 2.1 What it builds on (already built and tested, not yet merged)
| Piece | Status | Used for |
|---|---|---|
| `libs/qs_template` | 77 tests passing | Configuration, logging, errors, health and readiness, database sessions, JWT verification, revocation, outbox and idempotent consumers, Redpanda adapters, audit trail |
| `services/platform` (M0) | 34 tests passing | Signs the tokens the market API verifies; the pattern the market service copies (settings, migrations, image, compose entries) |
| `ci/scripts/python-ci.sh`, `migration-check.sh` | Working | Lint, types and tests with a throwaway PostgreSQL; migrations up, down and up |
| Deployment stack | Written, not yet deployed | PostgreSQL + TimescaleDB, Redis, Redpanda, gateway |

### 2.2 Vendor: Tiingo end-of-day
| Item | Finding | Consequence |
|---|---|---|
| Free-tier limits | Reported by third parties as **50 requests per hour, 1,000 per day, 500 unique symbols per month**; not confirmed on Tiingo's own site in October 2026 | Confirm on tiingo.com before go-live. The design keeps the budget configurable (`QS_TIINGO_REQUESTS_PER_HOUR`, default 45) |
| Request cost | One request returns any date range for one symbol, so a full history costs one request, as does a daily update | 40 instruments fit easily: under an hour for a full backfill, 40 requests per day after that |
| Data | Raw and adjusted OHLC, volume, dividend cash and split factor per session | Corporate actions come for free |
| Licence | Free plans are for personal, non-commercial use | Fine for the FYP; a paid licence is needed before charging users (already noted in the pricing work) |
| Account | Needs a free API key | The team signs up; the key goes into the encrypted secrets |

### 2.3 Infrastructure
| Item | Finding |
|---|---|
| Target host | The Oracle Always Free server (ARM). Every pinned image is multi-arch; `exchange_calendars`, `pandas` and `numpy` ship ARM wheels |
| TimescaleDB extension | Creating it needs a superuser, so `db-init` (superuser) creates it in `market`; the migration then only creates hypertables |
| Developer laptops | Disk space is tight; tests reuse the shared throwaway database, and heavy builds run on the CI server once it exists |

### 2.4 Draft code
A first draft of about ten files exists, uncommitted, on a local branch
(`feature/market-ingestion`): settings, models, calendar, cleaning gate, returns, Tiingo
adapter, rate limiter, pipeline, instrument service and API schemas. It follows this
design and will be split into the branches in section 10, reviewed and tested there,
rather than merged as one block.

---

## 3. Architecture

```
            ┌──────────────── market service (one image, four processes) ─────────────────┐
gateway ──▶ │ api        /api/market/*         (FastAPI, verifies JWT, role checks)        │
            │ scheduler  enqueues daily + catch-up runs (idempotent, safe to run twice)     │
            │ worker     claims and executes runs, one at a time (PostgreSQL advisory lock) │
            │ relay      publishes outbox events to Redpanda                                │
            └───────┬──────────────────────────────┬──────────────────────────┬─────────────┘
                    │                              │                          │
            market_db (PostgreSQL + TimescaleDB)  Redis (vendor budget,   Redpanda (events)
                                                   revocation list)
                    ▲
            market-migrate (one-off, before each deploy)
```

- **One image, four processes**: the same container starts as `serve`, `scheduler`,
  `worker` or `relay`, so every process always runs the same version.
- **Job queue in PostgreSQL, not Celery** (design change, recorded in the iteration plan):
  a run is a row; the API and scheduler insert rows; the worker claims them with
  `FOR UPDATE SKIP LOCKED` under an advisory lock. This needs no extra broker, cannot
  double-schedule (per-day idempotency keys), and a crashed run is recovered on the next
  claim. Celery remains an option for the heavier compute jobs of Iteration 2.
- **Pure-Python cleaning with exact decimals** instead of polars and pandera: the rules
  are simple, prices stay `Decimal` end to end (NFR-INT-001), and every rule is a small,
  readable, unit-tested function. `exchange_calendars` (which brings pandas) is used only
  for trading sessions and close times.

---

## 4. Data model (`market_db`) and migration protocol

### 4.1 Tables
| Table | Purpose | Key rules |
|---|---|---|
| `instrument` | Instrument master | Unique (symbol, exchange); status `active` or `retired` with consistent `retired_at`; symbol, currency and asset-class formats checked by the database; audited |
| `ingestion_run` | One row per run: mode, status, window, report, error | Status and mode sets checked; `idempotency_key` unique (scheduled runs collapse to one per day) |
| `ingestion_run_item` | Per-instrument outcome of a run | Status set checked; one row per run and instrument |
| `staging_bar` | Raw vendor records, untouched | Kept 90 days (cleanup job) |
| `bar` (hypertable) | Published clean bars | Key (instrument, session); `NUMERIC(23,8)` prices; the database refuses non-positive prices, `low > high`, open or close outside the range, negative volume; `revision`, `content_hash`, `quality_flags` |
| `bar_revision` | Previous values of corrected bars | Append-only history |
| `rejected_bar` | Rejected records with every rule they broke | Kept, never dropped |
| `data_gap` | Expected sessions with no clean bar | Resolved automatically when the bar arrives |
| `corporate_action` | Splits and dividends | Split factor > 0 |
| `return_series` (hypertable) | Log returns, adjusted returns, 20- and 60-day volatility | Recomputed from the earliest changed session |
| `replay_session` | Replay windows | Database check `end_time > start_time` (NFR-INT-003), speed bounds, status set |
| `outbox`, `processed_events` | Events | From the template |
| `audit_log` | Change history | From the template; `instrument` audited |

### 4.2 Migration protocol
1. **Every schema change is a new numbered Alembic revision** (`0001_market_schema`, then
   `0002_...`). Applied revisions are never edited; fixes go in a new revision.
2. **Every revision has a working `downgrade`.** `ci/scripts/migration-check.sh market`
   runs upgrade to head, downgrade to base, and upgrade again on an empty database; it
   must pass locally before pushing and runs in Jenkins on every pull request.
3. **The schema comes from migrations alone** (NFR-REC-001): no manual DDL, no
   `create_all` outside tests.
4. **Superuser-only steps live in `db-init`**, not in migrations: creating the database,
   its role, and the TimescaleDB extension. Migrations run as the service's own role.
5. **Migrations run before the new version starts**, through the `market-migrate`
   one-off container that the deploy runs; a failed migration stops the deploy.
6. **Backward-compatible changes only within a release**: add columns as nullable or with
   defaults; drop or rename in a later release once no running version uses them.
7. **Data migrations are separate revisions** from schema changes, and must be
   idempotent.
8. **The models in `models.py` match the migrations exactly**; a test compares them.

---

## 5. Ingestion run lifecycle

### 5.1 Triggers
| Trigger | Mode | Window |
|---|---|---|
| Scheduler, 22:30 UTC (after the US close) | `daily` | From 5 sessions before the last stored bar to today |
| Scheduler, 06:00 UTC | `catchup` | Same; picks up bars the vendor published late |
| Admin, `POST /ingestion-runs` | `manual` | Optional explicit window and instrument list |
| Admin, `POST /ingestion-runs` with `mode=backfill` | `backfill` | Explicit start date (default first run: 2015-01-02) |

The scheduler only enqueues; per-day idempotency keys mean running two schedulers cannot
create two daily runs.

### 5.2 Steps for each instrument (one transaction)
1. **Window**: an explicit window, or 5 sessions before the last stored bar to today, or
   the backfill start for a new instrument.
2. **Fetch** through the vendor adapter: shared hourly budget in Redis, 30 s timeout,
   up to 4 attempts with exponential backoff and jitter on timeouts, 5xx and 429
   (honouring `Retry-After`); unknown symbols and refused requests are not retried.
3. **Stage** the raw records in `staging_bar`.
4. **Clean** (section 6).
5. **Publish**: new sessions inserted; identical content (same hash) left alone; changed
   content becomes a new revision, with the previous values in `bar_revision`.
6. **Record quality**: rejected bars, new gaps, resolved gaps, corporate actions.
7. **Returns**: recomputed from the earliest new or revised session, using 61 sessions of
   history for the 60-day window.
8. **Events** through the outbox: `bar.ingested` (range, new and revised counts, gaps) and
   `bar.corrected` (sessions revised).

### 5.3 Run-level behaviour
| Situation | Behaviour |
|---|---|
| Two workers | Only the one holding the advisory lock executes; the other waits |
| Worker crashes mid-run | The lock is released with its connection; the next worker resets the run to pending and re-runs it safely |
| Vendor outage | After 5 consecutive vendor failures the circuit opens: remaining instruments are deferred, the run ends `partially_succeeded`, the catch-up run retries |
| Request budget used up | Remaining instruments deferred, not blocked for an hour |
| Unknown symbol | That instrument fails with the reason; the others continue |
| Same window run twice | No new rows, no new events |
| Run status | `succeeded` (all instruments succeeded or had no new data), `partially_succeeded`, `failed` |

---

## 6. The cleaning gate

| Rule | Severity | Outcome |
|---|---|---|
| `malformed` | reject | Missing or unparsable fields |
| `outside_window` | reject | A date the run did not ask for |
| `non_trading_day` | reject | Weekend or exchange holiday |
| `non_positive_price` | reject | Any price ≤ 0 |
| `ohlc_order` | reject | `low > high`, or open/close outside the range |
| `negative_volume` | reject | Volume < 0 |
| `duplicate_conflict` | reject | Same session twice with different values (all copies) |
| `duplicate_removed` | correct | Same session twice with identical values: one kept |
| `zero_volume` | flag | Published with the flag |
| `outlier` | flag (configurable: reject) | Absolute log return above 0.405 (about 50%); skipped on split days |
| missing session | record | Expected closed session with no clean bar: a data gap |

- Timestamps: every bar gets its session's actual close in UTC from the exchange calendar
  (handles daylight saving and early closes).
- A session counts as expected only once its close plus one hour has passed, so today's
  bar is not called missing before the vendor publishes it.
- The report per instrument: received, passed untouched, corrected, duplicates removed,
  rejected, counts per rule, flags, gaps. **Received = passed untouched + corrected +
  duplicates removed + rejected**, always (a property test checks it).
- The ruleset is versioned (`2026.10.1`) and stored on each run.

---

## 7. API (`/api/market`)

| Method and path | Roles | Purpose |
|---|---|---|
| `GET /instruments?status=` | all signed-in | List the instrument master |
| `POST /instruments` | admin | Add an instrument (409 if it exists) |
| `PATCH /instruments/{id}` | admin | Rename or annotate |
| `POST /instruments/{id}/retire` | admin | Retire (non-destructive) |
| `GET /instruments/{id}/bars?from&to` | all signed-in | Clean bars, paginated |
| `GET /instruments/{id}/returns?from&to` | all signed-in | Returns and volatility |
| `POST /ingestion-runs` | admin | Enqueue a manual run or backfill; answers 202 at once |
| `GET /ingestion-runs` | admin, quant, analyst | Run history |
| `GET /ingestion-runs/{id}` | admin, quant, analyst | Run detail, per-instrument items, report |
| `GET /ingestion-runs/{id}/rejected` | admin, quant, analyst | Rejected bars with reasons |
| `GET /data-quality` | admin, quant, analyst | Per instrument: last session, bar count, open gaps, flagged bars |
| `POST /replay-sessions` | admin, quant | Create a replay session (422 for an inverted window) |
| `GET /replay-sessions/{id}` | all signed-in | One replay session |
| `GET /health`, `GET /ready` | anyone | Liveness with build hash; readiness (database, Redis) |

The OpenAPI document is exported in CI and becomes the frontend's typed client (I1-41).

---

## 8. Operations

| Area | Plan |
|---|---|
| Configuration | `QS_*` variables: database, Redis, Tiingo key and budget, schedule times, lookback, backfill start, outlier threshold and policy |
| Secrets | `TIINGO_API_KEY` and `MARKET_DB_PASSWORD` in the SOPS-encrypted environment files |
| Deployment | Compose entries `market`, `market-worker`, `market-scheduler`, `market-relay`, `market-migrate`; `db-init` gains the `market` database, role and TimescaleDB extension; `ci/components.conf` gains `market` |
| Logs | Every line carries run id, instrument and vendor; never the API key |
| Metrics | Runs by status, run duration, rows by outcome, rejections by rule, vendor calls by status and latency, budget waits, circuit state, outbox backlog |
| Alerts (once Grafana exists) | Daily run failed; no successful run by 08:00 UTC; rejection rate over 5%; circuit open |
| Data retention | `staging_bar` older than 90 days deleted by a scheduled job; everything else kept |
| Runbook | Re-run a window, backfill an instrument, retire a delisted symbol, read a run report: added to the service README |

---

## 9. Testing

| Layer | What exactly |
|---|---|
| Unit: gate | One test per rule, pass and fail; duplicates identical and conflicting; outlier skipped on split days; outlier policy reject; timestamps in UTC across the DST change and on an early-close day; holidays never reported as gaps; today's bar not a gap before publication |
| Property: gate | For generated inputs: the gate never publishes `high < low` or a price ≤ 0; the report always adds up |
| Unit: returns | Log returns and volatility against hand-computed values; split days use adjusted prices |
| Unit: calendar | Sessions, close times, sessions before a date |
| Adapter | Recorded Tiingo responses: success, empty, 404, 429 with `Retry-After` then success, 500 then success, malformed JSON; the auth header is sent; normalisation of every field |
| Rate limiter | Budget respected across callers; gives up instead of waiting an hour |
| Database: pipeline | First run inserts; second identical run adds nothing and publishes nothing; a changed vendor value creates a revision and `bar.corrected`; rejected bars and gaps recorded; a gap resolves when the bar arrives; corporate actions stored; returns computed; one bad symbol gives `partially_succeeded`; the circuit breaker defers the rest; two workers never run at once; a crashed run is recovered |
| Database: rules | The database itself refuses `high < low` and an inverted replay window |
| API | Roles on every endpoint; trigger answers 202; run detail and rejected listing; replay validation |
| Planted-fault dataset | A fixed set of records with known defects (bad OHLC order, negative price, weekend date, identical and conflicting duplicates, a 60% jump, zero volume, a missing session); the run report must match the expected report exactly. Also the demo script for the Mid |
| Migrations | `migration-check.sh market`: up, down, up |
| End to end in DEV | Seed the universe, trigger a run with the real key on 3 symbols, check bars, report and events |

No test calls the real vendor; DEV and TEST use recorded responses unless the run is
explicitly triggered with a key.

---

## 10. Work breakdown

Each row is one `feature/*` branch, one pull request into `develop`, following the
git-flow skill (preflight, one-line commits, rebase merge when green). Branches stack in
this order.

| # | Branch | Contents | Done when | Depends on |
|---|---|---|---|---|
| 1 | `feature/market-schema` | Service skeleton, settings, models, migration `0001`, `db-init` changes, model-matches-migration test | Migration check passes; database rules tested | Template and platform merged |
| 2 | `feature/market-instruments` | Instrument master service and API, seed universe, audit, events | API tests pass; seed loads 40 instruments | 1 |
| 3 | `feature/market-cleaning-gate` | Calendar, gate, returns, with unit and property tests | Every rule tested; report always adds up | 1 |
| 4 | `feature/market-tiingo-adapter` | Source interface, Tiingo adapter, hourly budget, recorded fixtures | Adapter tests pass for every response type | 1 |
| 5 | `feature/market-pipeline` | Run queue, worker with lock and recovery, per-instrument transaction, revisions, quality records, returns, events, circuit breaker | Database pipeline tests pass, including idempotency and recovery | 2, 3, 4 |
| 6 | `feature/market-api-and-scheduler` | Run trigger and read endpoints, data quality, replay sessions, scheduler process, command line | API tests pass; scheduler creates one run per day | 5 |
| 7 | `feature/market-deployment` | Dockerfile, compose entries, secrets, components, README and runbook | DEV deploy: health through the gateway, smoke test green | 6, CI server up |
| 8 | `feature/market-planted-faults` | Planted-fault dataset and exact-report test, DEV end-to-end check with a real key | Report matches exactly; real run lands bars in DEV | 7 |

Branches 2, 3 and 4 can be built in parallel by different members after branch 1.

---

## 11. Decisions to confirm

| # | Decision | Recommendation |
|---|---|---|
| D1 | Price storage | `NUMERIC(23,8)`, volume `NUMERIC(28,8)` |
| D2 | Vendor corrections | Revisions plus `bar.corrected`, not "insert once" |
| D3 | Corporate actions | Store raw and adjusted series |
| D4 | Outliers | Flag and publish (configurable to reject) until a second vendor exists |
| D5 | Universe | The 40 instruments in the draft seed file (30 large-cap stocks, 10 ETFs) |
| D6 | Job queue | PostgreSQL queue instead of Celery for ingestion |
| D7 | Cleaning implementation | Pure Python with decimals instead of polars and pandera |
| D8 | Backfill start | 2015-01-02 (about ten years, enough for every analysis planned) |
| D9 | Draft code | Split into the branches above and reviewed, rather than discarded |

---

## 12. Risks

| Risk | Mitigation |
|---|---|
| Tiingo's real free limits differ from the reported ones | Confirm before go-live; the budget is a setting; deferral instead of failure |
| The free licence is non-commercial | Fine for the FYP; budget a paid feed before charging users |
| A vendor sends a bad bar after it was published | Revisions and `bar.corrected` let consumers correct downstream data |
| Disk space on developer laptops | Heavy runs on the CI server; caches cleaned after local checks |
| ARM build differences | All dependencies checked for ARM wheels; the CI server builds natively |
| Schedule slip | Branches 2, 3 and 4 run in parallel; correlation (I1-29) is the first thing cut |

---

## Sources for vendor limits

- QuantStart, "Evaluating Data Coverage with Tiingo": https://www.quantstart.com/articles/evaluating-data-coverage-with-tiingo/
- FindMyMoat, Tiingo listing: https://www.findmymoat.com/free/data-partners/tiingo
- FitGap, Tiingo: https://us.fitgap.com/products/022556/tiingo
