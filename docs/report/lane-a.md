# Lane A: Trading Engine and Platform

Draft chapter, Iteration 2 (window 16 Nov to 23 Dec 2026). State of the code: `develop` at
`6a65dba` (PR #111), 20 Nov 2026. Rows still open at that date are marked **pending** and
are completed before the final draft (J4, 18 Dec).

Lane A owns module M3, the event-sourced trading engine, from `trading_db` to the trading
pages; the platform kit that every new Iteration 2 service is built on (K1 to K3); the CI
pipeline, the DEV gates and the v0.2.0 release. This chapter describes the design of the
engine (section 1), the kit and the delivery pipeline (sections 2 and 3), traces each Lane A
requirement to the test that proves it (section 4), reports the test results (section 5),
and records the lane's decisions and design changes (section 6).

## 1. Design of the trading engine

### 1.1 Event sourcing

A quant binds a portfolio to one market environment (a historical replay or one path of a
simulation run), runs a strategy through it with costs and slippage, and reviews every
order, fill and valuation. Every state change is appended to one log per portfolio, the
`trade_event` table, and that log is the only source of truth. Holdings, fills, orders, the
value series and the current state are projections that can be recreated from the log at
any time, row for row (A-FR-11).

The log has eight versioned event types, each a strict Pydantic model
(`services/trading/src/qs_trading/domain/events.py`): `RUN_STARTED` (the full run
specification and the source fingerprint), `TICK`, `ORDER_PLACED`, `ORDER_REJECTED`,
`ORDER_FILLED`, `ORDER_EXPIRED`, `VALUED` and `RUN_COMPLETED`. Money travels as decimal
strings and is held as Python `Decimal` with half-even rounding: prices `NUMERIC(20,8)`, cash
`NUMERIC(20,2)` (NFR-INT-001).

The database enforces the log's properties itself, so they hold whatever code writes to it
(migration `services/trading/migrations/versions/0002_trading_schema.py`, A13, #89):

| Property | How it is enforced |
|---|---|
| Append-only for every role | `UPDATE`, `DELETE` and `TRUNCATE` revoked from the service role; a guard trigger refuses them for the owner and a superuser as well |
| Gap-free sequence | `seq` starts at 1 and each row must follow the previous one of its portfolio, across hypertable chunks; a repeated `(portfolio_id, seq)` is refused |
| Exactly one environment | CHECK on `portfolio`: a replay environment or a simulation run and path, never neither or both |
| Books never negative | CHECK `cash >= 0` on `portfolio_state_current`; fills must add up (price, quantity, costs) |
| Time series | `trade_event` and `portfolio_value` are TimescaleDB hypertables |

### 1.2 Functional core and the engine loop

The service is a functional core inside a thin shell. The core
(`qs_trading/domain/` and `qs_trading/engine/core.py`) is pure: no I/O, no clock, no random
source. The shell is the FastAPI process (`serve`), the engine worker that claims jobs from
the K1 queue (`worker`), and the outbox relay (`relay`, in-process on DEV to save memory).

```
  Trading pages (A18, pending)
        |  JWT + role
        v
  Traefik  /api/trading/*
        |
  +-----+---------------------- trading service ---------------------------+
  |  serve (FastAPI)  --202 + job id-->  job table (K1)  <--claim--  worker |
  |                                                                  |      |
  |      functional core: accounting, execution, costs, slippage,    |      |
  |      strategies (history-only view), engine core   <-------------+      |
  |                                                                  |      |
  |      MarketEnvironment port <-- file adapter (fixtures, demo)    |      |
  |                             <-- replay / synthetic HTTP (A17)    |      |
  |                                                                  v      |
  |  relay  <-- outbox --  trading_db: trade_event (hash chain), orders,    |
  |                        fills, holdings, value series, state, job        |
  +-------------------------------------------------------------------------+
```

One engine job runs one portfolio over its environment. Each session is processed in this
order (`engine/core.py`), and all of a session's writes commit in one transaction
(`engine/store.py`, A-NFR-07):

1. `RUN_STARTED` on the first session only.
2. `TICK` for the session, recording the source `seq` range consumed.
3. Open orders, oldest first, against this session's bar: market orders placed at the
   previous session fill at this open, resting limit orders fill when the range crosses
   them or expire. Each gives `ORDER_FILLED`, `ORDER_REJECTED` or `ORDER_EXPIRED`.
4. The strategy is called with a history-only view of sessions up to and including `t`.
5. Each returned intent is validated against cash, held shares and what open orders already
   commit; it gives `ORDER_PLACED` or `ORDER_REJECTED`.
6. `VALUED` at the close: cash plus every position at its latest close.
7. `RUN_COMPLETED` on the last session only.

The store then locks `portfolio_state_current` with `SELECT ... FOR UPDATE`, checks that the
session chains onto the committed head (`last_seq`, `last_hash`), inserts the events, folds
them into the projection tables with the same fold the rebuild uses, updates the state row
and writes outbox rows (`fill.executed`, `portfolio.updated`, `run.completed`) in the same
transaction (A-NFR-08).

Execution follows ADR 04 (section 6): daily bars, market orders at the next session's open
moved against the trader by slippage, cost `fixed + per_share x quantity + pct x notional`,
slippage fixed in basis points or volume based.

### 1.3 Ports and adapters

The engine reads market data through one port, `MarketEnvironment`
(`qs_trading/ports/market_environment.py`), with three operations: `activate()` freezes the
source and returns its fingerprint, `fingerprint()` reads it again, and
`ticks(after_seq, limit)` pages the ticks in a gap-free sequence ordered by session and
symbol. This follows Lane B's pull-based tick contract (ADR 01, C1) and its page limits
(default 500, at most 2,000 ticks).

| Adapter | Source | Status |
|---|---|---|
| File adapter (`adapters/file_environment.py`) | Contract fixtures (C3), the bundled demo and benchmark environments | Implemented (A14, aligned with the tick contract in #108) |
| Replay HTTP adapter (`adapters/http_environment.py`) | `market` service, historical environments (C2) | Implemented (A17, over K3's `ServiceClient`; contract-tested on fixtures until the live routes leave 501) |
| Synthetic HTTP adapter (`adapters/http_environment.py`) | `simulation` service, one path of a completed run | Implemented (A17, as above) |

Because the core only sees the port, the whole engine runs and is tested with no other
service up. The runner re-reads the fingerprint before each session commits; data that
changes under a running engine stops it with `FingerprintChanged` rather than mixing two
versions of the market into one log.

### 1.4 The hash chain

Every row of `trade_event` carries `hash_n = SHA-256(hash_(n-1) || canonical(event_n))`
(`qs_trading/domain/hashing.py`). The canonical form is compact JSON with keys sorted at
every level, holding the portfolio id, `seq`, type, version, payload and `event_time`.
Floats are refused, so money can only be hashed as a decimal string, and `event_time` is the
session's close taken from the market data, never the wall clock. Nothing in the chain
comes from a clock or a random source, so the same specification on the same source
fingerprint always ends on the same final hash (A-FR-12).

The chain serves three purposes:

- **Tamper evidence.** `verify_chain` (`projections/verify.py`) recomputes every hash from
  the row as stored and reports the first `seq` where a payload, time, type, link or order
  differs, or an event is missing.
- **Exact rebuild.** `rebuild` (`projections/rebuild.py`, A15, #96) verifies the chain,
  folds the log into fresh projections and compares them with the live tables, reporting
  `identical` or naming each differing row; `--apply` restores them. It is available as a
  command and as the admin route `POST /portfolios/{id}/rebuild`.
- **Crash resume (A-FR-13).** The committed log always ends on a session boundary. A
  restarted job recomputes the run in memory up to the committed `last_seq`, requires the
  recomputed hash to equal the stored one (else `ResumeMismatch`), and continues from the
  next session, so it appends exactly the events an uninterrupted run would have.

## 2. The platform kit (K1 to K3)

Iteration 2 adds three backend services (simulation, trading, risk) built by three people in
parallel. Without a shared base, each would solve background jobs, service wiring and
service-to-service calls separately, and the lanes would meet only at the end. The kit gives
every service the same proven base in week 1, so the lanes build domain logic from day 2.

| Kit item | What it provides | PR |
|---|---|---|
| K1 Job queue (`libs/qs_template/src/qs_template/jobs.py`) | A `job` table in each service's own database. Idempotent submit (unique key returns the existing job), single claim with `FOR UPDATE SKIP LOCKED`, leases with heartbeats and reclaim after a worker dies, fencing so a worker that lost its lease cannot overwrite the new owner's result, a bounded number of attempts | #73 |
| K2 Service scaffold (`scripts/new-service.sh`) | One command generates a service from `scripts/service-template/`: API with `/health`, job worker, outbox relay, Alembic with a first migration, tests, compose services, Traefik route, `ci/components.conf` entry, database and role in `db-init`, encrypted database password per environment. Generated simulation, trading and risk | #74, #76 |
| K3 ServiceClient and service tokens | Timeouts, retries with jittered backoff, circuit breaker, one `ServiceCallError`; DEV static token until real client-credential tokens (ADR 09) | Implemented (#85); real tokens in progress |

The trading service itself is a K2 output: its engine run is a K1 job (`engine.run`), which
gives idempotent run submission (`Idempotency-Key` header, 202 with the job id), progress
reporting and crash recovery without trading-specific queue code. A run that cannot succeed
on retry (missing fixture, changed fingerprint, unknown environment) fails permanently after
one attempt; transient failures are retried (#105).

## 3. CI, gates and the release path

Jenkins runs on an always-on Linux lab PC (since 18 Nov). Branches map to environments
through `ci/scripts/env-for-branch.sh`: `develop` deploys DEV, `test` TEST, `acceptance` ACC
and `main` PROD; any other branch runs checks only.

```
feature/a-*  -> lane/a-trading -> develop -> test -> acceptance -> main
 checks only     checks only     DEV        TEST     ACC          PROD
                                  |           |        |            |
                     dev-smoke gate   demo-spine gate  sign-off   approval, tag
```

| Stage | What it does |
|---|---|
| Prepare | `plan.sh` works out the environment, the version and a content hash per component from the paths listed in `ci/components.conf` |
| Pipeline scripts, Frontend CI, Backend CI | shellcheck; lint, type check, tests and build of the frontend; for every library and service in parallel `python-ci.sh` (ruff, mypy, pytest, including TimescaleDB tests) and, for services, a migration up/down/up check |
| Build images / Promote images | Only components whose content-hashed image does not yet exist are built; later environments promote the image verified on `develop` and refuse one that was never built there |
| Deploy | `deploy.sh` (image pulls retried, #111), `smoke.sh` (every service's `/health` through the gateway reports the expected build), then the Playwright gate for the environment, then on DEV the trading live check. A failure leaves the environment unverified; ACC and PROD roll back to the last good release |
| Acceptance sign-off, Approve production, Release | A person signs off ACC and approves PROD; `main` is tagged |

**Gates.** A green DEV deploy sets the `quantsim/dev-verified` status that branch protection
requires on the `develop -> test` pull request, so a failed Playwright smoke run blocks
promotion to TEST (A21, #91). The TEST stage runs Lane B's `demo-spine` suite in the same
way and gates ACC; until that suite exists the stage is skipped with a notice. The pr.sh
helper opens task pull requests into `lane/*` and lane pull requests into `develop` (A22,
#84).

**Trading live check** (`ci/scripts/trading_live_check.py`, #101, #106). After every DEV
deploy it runs a portfolio through the deployed API and engine on the bundled demo
environment: an unauthenticated write is refused, a repeated `Idempotency-Key` returns the
same job, a viewer may read the run but not start one, only one run per portfolio is active,
the whole log pages gap-free with an intact chain from `RUN_STARTED` to `RUN_COMPLETED`, and
fills, value series, state, verify, holdings, metrics and an admin rebuild (`identical`) all
end on the run's final hash. It then times the A-NFR-01 benchmark (section 5).

The live check found two defects that the unit and database tests had not:

- **Commit after response.** The request's database session committed after FastAPI had
  sent the response, so a client could receive 201 for a strategy and have its next request
  answered "no strategy has this id". The session now commits before the response; a test
  fails without the fix (`tests/api/test_commit_before_response.py`, #110). The same
  correction is being carried into the kit so that every generated service commits first
  (not yet on `develop` at `6a65dba`).
- **Registry pull timeouts.** A timeout pulling an image from the registry failed the whole
  DEV deploy; pulls are now retried (#111).

## 4. Requirements traceability

Status: **Implemented** (acceptance test in code and green in Jenkins), **Partial** (part of
the acceptance test is in place; the rest is named), **Pending** (not yet built). Test paths
are under `services/trading/tests/` unless stated; `::name` is the test function.

### 4.1 Functional requirements

| ID | Requirement (short) | Status | Proved by |
|---|---|---|---|
| A-FR-01 | Create, edit and list strategies of four kinds; bad params give 422 naming the field | Implemented (API); UI with A18 | `unit/test_strategies.py::test_params_save_and_reload`, `::test_bad_params_name_the_field`; `api/test_strategies_api.py::test_every_kind_saves_and_reloads_with_defaults_filled_in`, `::test_a_bad_body_is_a_422_naming_the_field`; `api/test_api_db.py::test_strategies_save_reload_list_and_edit` |
| A-FR-02 | Strategies see history only up to the current session | Implemented | `unit/test_history.py::test_reading_session_t_plus_one_raises`, `::test_a_strategy_that_peeks_fails_loudly` |
| A-FR-03 | Momentum rebalances under a max-position cap | Implemented | `unit/test_strategies.py::test_momentum_fixture_gives_hand_derived_orders`, `::test_momentum_trims_a_position_that_drifts_over_the_cap`; `property/test_strategy_properties.py::test_momentum_cap_holds_after_fills` |
| A-FR-04 | Portfolio bound to one replay environment or one simulation path, chosen from B's lists | Partial: binding enforced; picker pending (A18, C2) | `db/test_trading_db.py::test_a_portfolio_bound_to_neither_or_both_environments_is_refused`; `api/test_portfolios_api.py::test_a_binding_to_neither_or_both_is_refused`; `api/test_api_db.py::test_portfolios_bind_to_exactly_one_environment` |
| A-FR-05 | Market orders fill at the next open +/- slippage | Implemented | `unit/test_execution.py::test_buy_fills_at_next_open_plus_slippage_and_pays_every_cost`, `::test_never_fills_on_the_session_it_was_placed_in`; `unit/test_engine.py::test_buy_and_hold_sizes_and_fills_as_derived_by_hand` |
| A-FR-06 | Limit orders rest, fill when crossed, expire | Implemented | `unit/test_execution.py::test_gap_down_through_a_buy_limit_fills_at_the_open`, `::test_a_never_reached_limit_expires_on_its_last_session`; `unit/test_engine.py::test_a_gap_down_through_a_resting_limit_fills_at_the_open`, `::test_a_limit_the_range_never_reaches_expires_and_is_logged` |
| A-FR-07 | Orders without enough cash are rejected and logged | Implemented | `unit/test_execution.py::test_a_buy_short_of_cash_is_rejected_and_cash_is_unchanged`, `::test_a_gap_up_the_books_cannot_pay_is_rejected_at_the_fill`; `unit/test_engine.py::test_intents_that_cannot_be_placed_are_rejected_without_an_order`; `property/test_execution_properties.py::test_an_execution_always_applies_and_cash_stays_non_negative` |
| A-FR-08 | Fill cost = fixed + per-share x qty + pct x notional | Implemented | `unit/test_costs.py::test_fixed_component_only`, `::test_per_share_component_only`, `::test_percentage_component_is_charged_on_the_rounded_notional`, `::test_all_components_and_their_sum`; `property/test_execution_properties.py::test_costs_are_non_negative_and_add_up` |
| A-FR-09 | Slippage fixed bps or volume based | Implemented | `unit/test_slippage.py::test_buy_fills_higher`, `::test_buy_scales_with_participation`, `::test_participation_is_capped_at_the_bar_volume`; `unit/test_execution.py::test_volume_slippage_on_a_market_buy`; `property/test_execution_properties.py::test_slippage_is_never_favourable` |
| A-FR-10 | Gap-free, append-only, hash-chained log | Implemented | `db/test_trading_db.py::test_the_service_role_may_not_change_the_log`, `::test_the_guard_trigger_stops_the_owner_even_with_the_privilege_granted_back`, `::test_the_guard_trigger_stops_a_superuser`, `::test_a_repeated_portfolio_seq_is_refused_even_at_another_time`, `::test_a_gap_in_the_log_is_refused`; `unit/test_hashing.py`; `unit/test_verify.py` |
| A-FR-11 | Holdings, fills and value series are projections; rebuild equals live | Implemented | `db/test_rebuild_db.py::test_a_run_rebuilds_identical_with_its_final_hash`, `::test_changed_projection_rows_are_named_and_apply_restores_them`; `unit/test_projections.py::test_folding_session_by_session_equals_folding_the_whole_log` |
| A-FR-12 | Same spec on the same fingerprint gives the same final hash | Implemented (file adapter); J2 cross-adapter comparison pending A17 | `unit/test_engine.py::test_two_runs_end_on_the_same_hash`, `::test_one_changed_input_changes_the_final_hash`, `::test_another_fingerprint_changes_the_final_hash`; `property/test_strategy_properties.py::test_every_kind_is_deterministic` |
| A-FR-13 | A killed worker resumes to an identical log | Implemented | `db/test_engine_db.py::test_a_crash_then_resume_gives_the_identical_log` (crash after sessions 1, 5, 9); `unit/test_engine_runner.py::test_a_crashed_run_resumes_to_the_identical_log`, `::test_resuming_with_a_changed_spec_is_refused`; `unit/test_engine.py::test_replay_refuses_a_log_it_cannot_reproduce` |
| A-FR-14 | Run metrics stored and served, computed with `qs_quant.metrics` | Partial: trades and costs served; return, volatility, Sharpe, drawdown pending Lane C's K6 | `api/test_projections_api.py::test_metrics_count_trades_and_costs_and_leave_the_ratios_pending`, `::test_a_metrics_calculator_fills_in_the_ratios_it_computes` |
| A-FR-15 | State as of any seq can be read | Implemented | `db/test_rebuild_db.py::test_the_state_as_of_a_seq_equals_the_projection_there`; `unit/test_projections.py::test_the_state_as_of_each_session_end_equals_the_engines`; `api/test_projections_api.py::test_the_state_as_of_the_last_seq_is_the_state_row` |
| A-FR-16 | Five trading pages in the prototype layout; Trade Replay at 1x, 5x, 20x | Pending (A18) | — |
| A-FR-17 | Job library: single claim, lease reclaim, idempotent submit | Implemented | `libs/qs_template/tests/test_jobs.py::test_two_open_claims_never_take_the_same_job`, `::test_many_workers_claim_every_job_exactly_once`, `::test_a_dead_workers_job_is_reclaimed_and_the_old_owner_is_fenced`, `::test_duplicate_submit_returns_the_same_job`, `::test_concurrent_duplicate_submits_create_one_job` |
| A-FR-18 | Scaffold generates a runnable service in one command | Implemented; database-role isolation enforced in `db-init` but not yet tested automatically | `scripts/service-template/tests/test_service.py`; `test_service.py::test_health_reports_the_build`; `ci/scripts/smoke.sh` (simulation, trading, risk `/health` through the gateway on every deploy) |
| A-FR-19 | Workers call other services without a user token | Partly met: K3 merged (#85), HTTP feeds use it (A17); real tokens due 2 Dec | — |
| A-FR-20 | Playwright DEV smoke gates promotion to TEST | Implemented | `frontend/e2e/dev-smoke/smoke.spec.ts` (3 tests); `ci/scripts/playwright-gate.sh`; `quantsim/dev-verified` required on the `develop -> test` PR |
| A-FR-21 | pr.sh lane support; Jenkins runs both Playwright gates | Implemented; demo-spine gate active once Lane B's suite exists | pr.sh (A22, #84), verified by use; Jenkinsfile Deploy stage, `ci/scripts/playwright-gate.sh` |
| A-FR-22 | CI builds only changed services; v0.2.0 promoted to main | Partial: content-hash builds in place and used for v0.1.2 (#94, #95, #98); v0.2.0 release pending (A19, 23 Dec) | `ci/components.conf`, `ci/scripts/plan.sh`, `ci/scripts/image-exists.sh` |

### 4.2 Non-functional requirements

| ID | Requirement (short) | Status | Proved by |
|---|---|---|---|
| A-NFR-01 | 40 instruments x 252 sessions under 60 s on DEV | Implemented | `unit/test_performance.py`; `db/test_performance_db.py::test_a_persisted_40_by_252_run_finishes_inside_the_budget`; DEV live check: 4.0 s |
| A-NFR-02 | Run submit 202 under 800 ms p95 | Pending (load script); 202 behaviour tested | `api/test_runs_api.py::test_a_submit_is_202_and_a_repeated_key_returns_the_same_job` |
| A-NFR-03 | Projection and metrics reads under 2 s p95 | Pending (load script) | — |
| A-NFR-04 | Decimal in domain, NUMERIC in DB, no float | Partial: refused at runtime and in the schema; lint rule pending | `unit/test_money.py::test_float_and_bool_are_refused`; `unit/test_hashing.py::test_floats_and_bad_seqs_are_refused`; `db/test_schema_definitions.py::test_money_columns_use_fixed_precision`; `api/test_api_roles.py::test_money_is_a_decimal_string_in_the_openapi_document` |
| A-NFR-05 | Trade log append-only for everyone | Implemented | `db/test_trading_db.py` tampering tests as service role, owner and superuser |
| A-NFR-06 | Same inputs give an identical log and hash | Implemented (two runs compared event by event) | `unit/test_engine.py::test_two_runs_end_on_the_same_hash`; `property/test_strategy_properties.py::test_every_kind_is_deterministic` |
| A-NFR-07 | One transaction per session; crash-resume identical | Implemented | `db/test_engine_db.py::test_a_crash_then_resume_gives_the_identical_log` |
| A-NFR-08 | Outbox commits with state; redelivery changes nothing | Implemented | `db/test_engine_db.py::test_a_run_persists_a_chained_log_with_its_state_and_outbox`; `libs/qs_template/tests/test_messaging.py::test_duplicate_delivery_changes_nothing`, `::test_relays_in_parallel_never_publish_an_event_twice` |
| A-NFR-09 | Timeout, retry budget and circuit breaker on every remote call | Met for the market and simulation feeds (K3 #85, A17) | — |
| A-NFR-10 | Role checked on every route; analyst and viewer writes 403 | Implemented | `api/test_api_roles.py::test_every_route_has_a_declared_rule`, `::test_every_route_allows_exactly_the_declared_roles`; `api/test_api_db.py::test_every_route_allows_exactly_the_declared_roles`; live check (viewer 403) |
| A-NFR-11 | Each service role reaches only its own database; static token removed before TEST | Partial: `REVOKE ALL ... FROM PUBLIC` per database in `db-init`; connection test and TEST token check pending | `deploy/compose/docker-compose.yml` (`db-init`) |
| A-NFR-12 | OpenAPI exported on each merge for K4's type check | Pending (with K4) | — |
| A-NFR-13 | Services start from env vars only; missing config fails at start-up | Implemented | `libs/qs_template/tests/test_config.py::test_refuses_to_start_without_required_settings`; `unit/test_demo_environments.py::test_a_missing_directory_stops_the_worker_from_starting` |
| A-NFR-14 | Structured logs; job duration, queue depth, outbox backlog exposed | Pending | — |
| A-NFR-15 | Memory limits, `OMP_NUM_THREADS=1`, relay in-process on DEV, disk headroom | Partial: compose limits and embedded relay in place; Jenkins disk check pending | `deploy/compose/docker-compose.yml`; `test_service.py::test_embedded_mode_runs_the_worker_and_relay_in_process` |
| A-NFR-16 | No TEST without green Playwright smoke; no ACC without B's spine | Partial: TEST gate active; ACC gate wired, waits for Lane B's suite | Jenkinsfile Deploy stage; `ci/scripts/playwright-gate.sh` |
| A-NFR-17 | Every trading page has loading, empty, error and 403 states | Pending (A18) | — |

### 4.3 Summary

| | Implemented | Partial | Pending | Total |
|---|---|---|---|---|
| A-FR | 17 | 3 | 2 | 22 |
| A-NFR | 7 | 4 | 6 | 17 |

Implemented rows include A-FR-01 and A-FR-21, whose UI or Lane B parts follow later. Still
open on the functional side: A-FR-14's ratios (Lane C's K6), A-FR-16 (trading pages, A18),
A-FR-19 (real service tokens, K3 follow-up), A-FR-22's v0.2.0 release (A19), and
A-FR-04's environment picker (A18 with C2).

## 5. Test results

### 5.1 Counts per level

Test functions in `services/trading/tests/` at `6a65dba` (parametrised tests run as several
cases, so Jenkins reports more cases than functions):

| Level | Folder | Files | Test functions | What it covers |
|---|---|---|---|---|
| Unit and fixture | `unit/` | 19 | 236 | Money, accounting, costs, slippage, execution rules, strategies, history view, hashing, verification, engine core and runner, projections, file adapter, contract fixtures, CLI, performance in memory |
| Property (Hypothesis) | `property/` | 3 | 11 | Books balance after every fill, cash never negative, costs add up, slippage never favourable, limit respected, momentum cap, determinism per kind |
| Database (TimescaleDB) | `db/` | 6 | 49 | Guard trigger, revoked privileges, CHECKs, migration up/down/up, schema equals models, persisted run, crash-resume, rebuild, job failures, A-NFR-01 |
| API | `api/` | 10 | 48 | Role matrix per route, idempotent submit, one active run, paging, projections, rebuild, commit before response; `*_db.py` files on a real database |
| Service | `test_service.py` | 1 | 4 | Health, embedded worker and relay |
| **Total** | | **39** | **348** | |

In Jenkins the database-marked suite (the `db/` folder plus the three `api/*_db.py` files)
passed 58 of 58 cases on TimescaleDB. The DEV Playwright smoke suite passed 3 of 3 against
the deployed site. The kit's job-queue tests are in `libs/qs_template/tests/test_jobs.py`
(11 functions).

### 5.2 Determinism and crash-resume

- **Determinism.** Two runs of the same specification on the same fixture produce the same
  hash for every event and the same final hash; changing one input (a cost parameter, the
  slippage, a strategy parameter, the capital, the portfolio id) or the source fingerprint changes the final hash
  (`unit/test_engine.py`). Each of the four strategy kinds is checked for identical orders
  over generated histories (`property/test_strategy_properties.py`), and a caller's decimal
  context does not change the orders.
- **Crash-resume.** On a real TimescaleDB the engine job is killed after sessions 1, 5 and 9
  of a 10-session run, then resumed; in every case the resumed log equals an uninterrupted
  run's log row for row, including the final hash
  (`db/test_engine_db.py::test_a_crash_then_resume_gives_the_identical_log`). A resume with
  a changed specification is refused rather than producing a mixed log.
- **Live.** Every DEV deploy runs a portfolio on the demo environment: 26 events, intact
  chain, and projections, verify and an admin rebuild all identical on the final hash.

### 5.3 Performance (A-NFR-01)

A momentum run over the bundled 40-instrument, 252-session benchmark environment, persisted
to `trading_db` with one transaction per session, finished on DEV in **4.0 s** against the
60 s limit: 252 sessions, 1,438 events, chain intact. The same run is timed in memory
(`unit/test_performance.py`) and on the Jenkins database (`db/test_performance_db.py`).
Lane C's performance study records the figure.

### 5.4 J2 hash comparison

Pending (J2, Fri 4 Dec). The comparison runs the same portfolio over the same historical
window through the file adapter (recorded C3 fixture) and through the replay HTTP adapter
(A17) and requires equal final hashes. The prerequisite is in place: the replay fixture
reports its declared fingerprint and a buy-and-hold run over it records it
(`unit/test_contract_fixtures.py::test_a_buy_and_hold_run_over_the_replay_fixture_records_the_xxh3_fingerprint`).

### 5.5 Known limits

- **Rewritten log.** Someone with database superuser rights who disables the guard trigger
  and rewrites a row together with every hash after it produces a chain that verifies on its
  own. Only the recorded final hash (in the `run.completed` event and the run's job result)
  exposes the change (`unit/test_verify.py::test_a_rewritten_tail_verifies_but_ends_on_another_hash`).
  An external anchor for final hashes would close this; it is out of scope for Iteration 2.
- **Daily bars only.** No intraday execution or partial fills; a gap fills at the open.
- **Crash points.** The crash-resume test kills the job at three fixed sessions, not a random
  one; resume is session-granular by construction, so the boundaries tested are the ones
  that can occur.
- **DEV data.** The live check runs on the bundled demo environment until the HTTP adapters
  (A17) and real tokens (K3) land.
- **Public addresses.** DEV and TEST APIs are reached through free Cloudflare quick tunnels,
  whose URLs change when a tunnel restarts; the deploy scripts read the current URL each
  time.

## 6. Decisions and design changes

### 6.1 Lane A ADRs

| ADR | Decision | Status |
|---|---|---|
| 04 Execution timing (`docs/adr/0004-execution-timing.md`) | Daily bars; market orders fill at the next session's open with adverse slippage; limit orders rest from `t + 1`, fill at the open on a gap or at the limit when crossed, and expire; placement and fill-time cash checks; costs and slippage as in A-FR-08/09 | Accepted, 20 Nov |
| 05 Strategy type (`docs/adr/0005-strategy-type.md`) | `kind` plus `params` JSONB; four built-in kinds with strict parameter models; pure, history-only strategies; a strategy is locked (409) once a portfolio using it has run | Accepted, 20 Nov |
| 09 Service tokens (`docs/adr/0009-service-tokens.md`) | Workers call through K3 `ServiceClient`; DEV static token until platform client-credential tokens (2 Dec); static token refused outside local and dev, removed before TEST | Accepted, 20 Nov |

### 6.2 Design changes since the Mid Report

| Area | Mid Report / Iteration 1 plan | Now | Reason |
|---|---|---|---|
| Market input | Tick replay (Binance ticks named in `docs/iteration-plan.md`) | Daily adjusted bars through the pull-based tick port; next-open execution | ADR 01, 04, 08: one data shape for replay and simulation, and no look-ahead |
| Metrics | Computed in the trading service | Formulas from Lane C's `qs_quant.metrics` (K6); trading stores and serves them | Rebalanced lane load; one implementation of the maths |
| Service base | Each service hand-built as in Iteration 1 | K1 job queue, K2 scaffold, K3 client shared by all new services | Three services built in parallel in one iteration |
| Strategy model | Not fixed | Built-in kinds with typed params, locked after a run | ADR 05: reproducibility from the stored spec |
| Run control | One run per request | Idempotent submit, one active run per portfolio, permanent vs transient job failures (#105) | Found while building the live check |
| Delivery | Promotion gated by smoke tests | Playwright DEV gate before TEST, trading live check on every DEV deploy, content-hashed images, Jenkins on an always-on lab PC with a git mirror (#93) | Iteration 1 follow-up C2; slow network at the lab PC |
| Scope | News ingestion and dashboard projections in Iteration 2 | Deferred | ADR 10 (Lane C) |

## 7. Tables 12 and 25 (member and responsibilities)

To be completed by Ali.

## 8. Tool use disclosure

To be completed by Ali.
