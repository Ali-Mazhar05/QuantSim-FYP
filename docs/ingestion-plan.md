# Ingestion Engine Plan (M1 Market Data)

The detailed plan for building QuantSim's market-data ingestion engine: what it must do,
what it builds on, how it is designed, how it is tested and deployed, and the order of
work.

Task ids (I1-xx) refer to [iteration-plan.md](iteration-plan.md). Requirement ids
(FR-MKT-xxx) refer to the requirements specification.

---

## 0. Status (2026-10-14)

Plan revision 2. The CI/CD server and the platform service are running, and the first
layers of the market service are built on draft pull requests that are not merged yet.

| Layer | State | Where |
|---|---|---|
| `market_db` schema, service skeleton, database rules | Built, 19 tests | PR #14, `feature/market-schema` |
| Trading calendar, cleaning gate, returns and volatility | Built, 55 tests | PR #18, `feature/market-cleaning-gate` |
| Generated ERD, kept in step with the schema by a test | Built, 64 tests in total | PR #31, `feature/market-erd` |
| PRD, epics, stories, OpenSpec change `add-market-ingestion` | Written | PR #15, `feature/market-user-stories` |
| Instrument master, Tiingo adapter, run queue and worker, publishing, scheduler, read API, deployment, planted-fault demo | **Not started** | section 10 |

The pull requests are stacked (#14, then #18, then #31) and still target branches that
are already merged. Step 0 of section 10 re-points and merges them first.

What changed in this revision, and why:

| Change | Reason |
|---|---|
| Gap grace period is close plus 12 hours (was one hour) | Tiingo end-of-day data often lands late; one hour raised a false "missing bar" every day. The merged code uses 12 hours, so this document now agrees with it (D10) |
| Scheduled runs are enabled on one environment only, with one vendor budget shared across environments | One free key allows 50 requests an hour; two schedulers at 45 each would exhaust it (D11, D12) |
| Section 3.1 states where scheduled runs execute | Until an always-on server exists, scheduled runs happen only while someone hosts Jenkins |
| Correlation series (FR-MKT-004) has its own work item, marked stretch | It is a Core requirement that Risk and TDA depend on and had no task |
| Work breakdown carries the real branch names, pull request numbers and a cut order | Section 10 now shows delivered and remaining work separately |

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
| Correlation matrices (FR-MKT-004, I1-29) | Work item 9 in section 10, a stretch goal. If it is cut it moves to Iteration 3 with TDA, which needs it as input (FR-RSK-011) |
| Versioned baskets (FR-MKT-005, Extended) | With correlation, whenever it is built |
| News ingestion (FR-MKT-006) | Iteration 2 |
| Replay playback and tick streaming (FR-MKT-007) | Iteration 2 |
| Second vendor for cross-checking outliers | When a second free source is chosen |

---

## 2. Investigation findings

### 2.1 What it builds on (merged and running)
| Piece | Status | Used for |
|---|---|---|
| `libs/qs_template` | Merged, tested in CI | Configuration, logging, errors, health and readiness, database sessions, JWT verification, revocation, outbox and idempotent consumers, Redpanda adapters, audit trail |
| `services/platform` (M0) | Merged, 103 tests, deployed on DEV and TEST | Signs the tokens the market API verifies; the role matrix the market routes reuse; the pattern the market service copies (settings, migrations, image, compose entries) |
| `ci/scripts/python-ci.sh`, `migration-check.sh` | Working in Jenkins | Lint, types and tests with a throwaway PostgreSQL; migrations up, down and up |
| Deployment stack | Running on DEV and TEST | PostgreSQL + TimescaleDB, Redis, Redpanda, gateway |

### 2.2 Vendor: Tiingo end-of-day
| Item | Finding | Consequence |
|---|---|---|
| Free-tier limits | Reported by third parties as **50 requests per hour, 1,000 per day, 500 unique symbols per month**; not confirmed on Tiingo's own site in October 2026 | Confirm on tiingo.com before go-live. The design keeps the budget configurable (`QS_TIINGO_REQUESTS_PER_HOUR`, default 45) |
| Request cost | One request returns any date range for one symbol, so a full history costs one request, as does a daily update | 40 instruments fit easily: under an hour for a full backfill, 40 requests per day after that |
| Data | Raw and adjusted OHLC, volume, dividend cash and split factor per session | Corporate actions come for free |
| Licence | Free plans are for personal, non-commercial use | Fine for the FYP; a paid licence is needed before charging users (already noted in the pricing work) |
| Account | Needs a free API key | One shared key for the team, stored as `TIINGO_API_KEY` in the encrypted secrets with `ci/scripts/set-secret.sh`; never in a file, a log or a test fixture |
| Verification | The limits above are third-party figures | Branch 4 in section 10 includes a one-symbol vendor check that records the real response headers and the actual rate limit before the adapter is trusted |

### 2.3 Infrastructure
| Item | Finding |
|---|---|
| Target host | The Oracle Always Free server (ARM). Every pinned image is multi-arch; `exchange_calendars`, `pandas` and `numpy` ship ARM wheels |
| TimescaleDB extension | Creating it needs a superuser, so `db-init` (superuser) creates it in `market`; the migration then only creates hypertables |
| Developer laptops | Disk space is tight; tests reuse the shared throwaway database, and heavy builds run on the CI server once it exists |

### 2.4 What was built from the draft
The first draft was split into reviewed branches, as planned. Schema and skeleton,
calendar, cleaning gate and returns are built and tested (section 0). The Tiingo adapter,
rate limiter, pipeline and instrument service from the draft are not merged and will be
rebuilt branch by branch against the schema that now exists.

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

### 3.1 Where scheduled runs execute
The scheduler is only useful while the process runs, and today the backend runs on
whichever laptop is hosting Jenkins. So:

- **Scheduled runs happen only while someone hosts.** The 06:00 UTC catch-up run exists
  to recover a missed 22:30 run, and a missed day is filled by the next run's five-session
  overlap, so a host that was off for a day loses nothing permanently.
- **One scheduler across all environments.** It is enabled on TEST only (`QS_SCHEDULER_ENABLED`);
  DEV and ACC run manual and backfill runs on demand. This keeps the shared vendor
  budget safe (D11).
- **A success metric must not depend on a host that does not exist.** "Ten days of
  scheduled runs" is replaced by "at least three scheduled runs plus a manual-run log with
  the run reports", until an always-on server is provisioned (D13).
- **An always-on server remains the target** (Oracle Always Free, or any small VM). When
  it exists, moving ACC and PROD there needs no code change, only compose targets.

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
create two daily runs. It is enabled on TEST only (section 3.1). "Today" is the UTC date.
A run whose window holds no expected session (a weekend, a holiday) ends `succeeded`
with zero new sessions and no events.

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
| Backfill competes with the daily run | One request per active instrument per scheduled run is reserved out of the hourly budget, so a backfill can never starve the daily run |
| Vendor refuses the key (HTTP 401) | The whole run fails as `vendor_auth` with no retries; it is not counted toward the circuit |
| Two runs for one instrument and window | The second is refused with 409 and the id of the active run |
| Unknown symbol | That instrument fails with the reason; the others continue |
| A vendor correction fails the gate | The published bar is kept, a rejected bar is recorded with the reason, and no revision or `bar.corrected` is produced |
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
- A session counts as expected only once its close plus 12 hours has passed, so today's
  bar is not called missing before the vendor publishes it. The earlier one-hour figure
  raised a false gap every day because Tiingo end-of-day data often arrives late; the
  built gate uses 12 hours (`PUBLICATION_GRACE`) and this document now agrees (D10).
- Every published bar and revision carries its provenance: run id, vendor and ruleset
  version.
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
git-flow skill (preflight, one-line commits, merge commit when green).

**Status key:** ✅ built (draft PR, not merged) · ⬜ not started · ✂ cut candidate.

### Step 0: land what is built
The four open pull requests target branches that are already merged. Before anything new
starts they are re-pointed at `develop` and merged in this order, each with a green
Jenkins run:

| Order | PR | Branch | Action |
|---|---|---|---|
| 1 | #14 | `feature/market-schema` | Re-point at `develop`, merge |
| 2 | #18 | `feature/market-cleaning-gate` | Re-point at `develop` after #14, merge |
| 3 | #31 | `feature/market-erd` | Re-point at `develop` after #18, merge |
| any | #15 | `feature/market-user-stories` | Docs only; re-point at `develop`, merge any time |

### Built and remaining work
| # | Branch | Contents | Done when | Depends on | State |
|---|---|---|---|---|---|
| 1 | `feature/market-schema` | Service skeleton, settings, models, migration `0001`, model-matches-migration test | Migration check passes; database rules tested | Template and platform merged | ✅ PR #14 |
| 2 | `feature/market-cleaning-gate` | Calendar, gate, returns, with unit and property tests | Every rule tested; report always adds up | 1 | ✅ PR #18 |
| 2b | `feature/market-erd` | ERD generator and committed diagram, kept in step by a test | Test fails when the diagram is stale | 2 | ✅ PR #31 |
| 3 | `feature/market-instruments` | Instrument master service and API, seed universe, audit, events, role-by-route matrix test | API tests pass; seed loads 40 instruments; every route refuses the wrong role | 1 | ⬜ |
| 4 | `feature/market-tiingo-adapter` | Source interface, Tiingo adapter, shared hourly budget, fixture source, one-symbol vendor check, guard that tests never reach the real host | Adapter tests pass for every response type; vendor check records the real limits | 1, key stored | ⬜ |
| 5 | `feature/market-pipeline` | Run queue, worker with lock and recovery, per-instrument transaction, revisions, quality records, returns, events, circuit breaker | Database pipeline tests pass, including idempotency and recovery | 2, 3, 4 | ⬜ |
| 6 | `feature/market-api-and-scheduler` | Run trigger and read endpoints, data quality, replay sessions, tick schema, scheduler (TEST only), command line | API tests pass; scheduler creates one run per day | 5 | ⬜ |
| 7 | `feature/market-deployment` | `db-init` for `market`, Dockerfile, compose entries, secrets, components, README and runbook | DEV deploy: health through the gateway, smoke test green | 6 | ⬜ |
| 8 | `feature/market-planted-faults` | Planted-fault dataset and exact-report test, DEV end-to-end check with a real key | Report matches exactly; real run lands bars in DEV | 7 | ⬜ |
| 9 | `feature/market-correlation` | Baskets and rolling correlation matrices in one request, fingerprinted (FR-MKT-004) | One request returns every window's matrix; identical windows give identical fingerprints | 5 | ✂ stretch |
| 10 | `feature/market-corporate-actions` | Splits and dividends from the vendor, adjusted series (FR-MKT-010) | Adjusted series served without overwriting raw bars | 5 | ✂ |
| 11 | `feature/market-symbol-directory` | Nasdaq symbol directory validation on instrument add | No live download in tests | 3 | ✂ first to cut |

Branches 3 and 4 can be built in parallel after step 0.

### Cut order
If the schedule slips, cut in this order, and record the cut in the progress log:
1. Symbol directory (11)
2. Corporate actions (10)
3. Tracing (I1-17)
4. Correlation (9), which then moves to Iteration 3 with TDA
5. The catch-up run, and a backfill bounded to one or two years

**Never cut:** the cleaning gate, idempotent publication, the planted-fault demo and the
role checks on every route. They are the Mid demonstration.

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
| D9 | Draft code | Split into the branches above and reviewed, rather than discarded (done for schema, gate and returns) |
| D10 | Gap grace period | Close plus 12 hours, not one hour; matches the built gate |
| D11 | Which environment schedules | TEST only. DEV and ACC take manual and backfill runs |
| D12 | Vendor budget | One hourly budget per API key, shared by every environment through Redis, with one request per active instrument per scheduled run reserved |
| D13 | Scheduled-run success metric | At least three scheduled runs plus a manual-run log, until an always-on host exists |
| D14 | Correlation (FR-MKT-004) | Own work item, stretch; moves to Iteration 3 if cut |
| D15 | Vendor key | One shared Tiingo key as `TIINGO_API_KEY` in the encrypted secrets; the limits are verified by the vendor check in branch 4 |

---

## 12. Risks

| Risk | Mitigation |
|---|---|
| Tiingo's real free limits differ from the reported ones | Confirm before go-live; the budget is a setting; deferral instead of failure |
| The free licence is non-commercial | Fine for the FYP; budget a paid feed before charging users |
| A vendor sends a bad bar after it was published | Revisions and `bar.corrected` let consumers correct downstream data |
| Disk space on developer laptops | Heavy runs on the CI server; caches cleaned after local checks |
| ARM build differences | All dependencies checked for ARM wheels; the CI server builds natively |
| Schedule slip | Branches 3 and 4 run in parallel; follow the cut order in section 10 |
| No always-on host, so scheduled runs stop when nobody hosts | Catch-up run and five-session overlap recover missed days; success metric relaxed (D13); an always-on server stays the target |
| Two environments exhaust one Tiingo key | One shared budget per key and a scheduler on TEST only (D11, D12) |
| A schedule too large for the people available | Cut order in section 10; reviews and pairing spread across members; the pull request chain is merged first so work does not stack up |
| Pull request chain targets merged branches and carries old red statuses | Step 0 re-points and re-runs them before new work starts |
| The Tiingo key leaks through a log, fixture or file | Stored only through `set-secret.sh`; redacted from logs (observability tasks); a CI guard fails tests that open a connection to the vendor |

---

## Sources for vendor limits

- QuantStart, "Evaluating Data Coverage with Tiingo": https://www.quantstart.com/articles/evaluating-data-coverage-with-tiingo/
- FindMyMoat, Tiingo listing: https://www.findmymoat.com/free/data-partners/tiingo
- FitGap, Tiingo: https://us.fitgap.com/products/022556/tiingo
