# Tasks

Each numbered group is one `feature/*` branch and one pull request into `develop`, in dependency order. Groups 3, 4 and 5 can run in parallel after group 2. Story ids refer to `docs/bmad/planning-artifacts/epics.md`. Prerequisites outside this change: `feature/service-template` and `feature/platform-service` merged with green CI (stories 2.1 to 2.7).

## 1. Market schema (feature/market-schema; story 3.1)

- [ ] 1.1 Create the `services/market` skeleton on `libs/qs_template` with `QS_*` settings and `/api/market/health` (build Content hash) and `/api/market/ready` (503 when the database or Redis is down); verify with an API test for both endpoints
- [ ] 1.2 Add `db-init` steps for the `market` database, the `market` role and the TimescaleDB extension; verify `db-init` runs twice without error on a fresh stack
- [ ] 1.3 Write Alembic revision `0001_market_schema` and matching models for `instrument`, `ingestion_run`, `ingestion_run_item`, `staging_bar`, `bar` and `return_series` (hypertables), `bar_revision`, `rejected_bar`, `data_gap`, `corporate_action`, `replay_session`, `outbox`, `processed_events`, `audit_log`, with prices `NUMERIC(23,8)`, volume `NUMERIC(28,8)`, provenance columns, Run item deferral fields and a planted-Instrument marker; verify `ci/scripts/migration-check.sh market` (upgrade head, downgrade base, upgrade head) passes locally
- [ ] 1.4 Add the model-matches-migration test and database-rule tests (refuse non-positive price, `low > high`, open or close outside range, negative volume, duplicate symbol and exchange, unknown status, inverted replay window, speed outside (0, 1000], split factor not above 0); verify all pass
- [ ] 1.5 Done when: the migration check passes in Jenkins on the pull request and every database-rule test is green

## 2. Instrument master (feature/market-instruments; stories 3.2, 3.3)

- [ ] 2.1 Implement add, annotate, retire and list routes with declared Roles, HTTP 409 naming the existing id and status, idempotent retire, Audit entries and `instrument.created` / `instrument.retired` outbox Events; verify with API tests for success, 409, 403 for quant, analyst and viewer, 401 without a token, and retire twice
- [ ] 2.2 Add the role-by-route matrix test for market routes (every route, four Roles, expected 2xx or 403) and the route-declaration test; verify both fail when a route lacks a declaration
- [ ] 2.3 Implement the idempotent seed command for the 40-Instrument universe (30 equities, 10 ETFs) that does not read the Symbol directory; verify a test seeds 40 and a second run adds 0
- [ ] 2.4 Done when: API and seed tests pass in CI and the event schemas for `instrument.created` and `instrument.retired` are in `contracts/events/`

## 3. Vendor adapter and budget (feature/market-tiingo-adapter; stories 4.1, 4.2)

- [ ] 3.1 Implement the source interface and Tiingo adapter (30 s timeout, up to 4 attempts with backoff and jitter on timeouts, 5xx and 429 honouring `Retry-After`, no retry on unknown symbol or refusal, `vendor_auth` on 401 or 403, `malformed_response` on bad payloads, normalization to `Decimal`); verify with recorded-response tests for success, empty, 404, 429 then success, 500 then success, malformed JSON, and the auth header
- [ ] 3.2 Implement the fixture source that serves recorded responses, selectable by configuration; verify a test that no network call is made when it is selected
- [ ] 3.3 Implement the shared Redis hourly budget keyed by API key (default 45), the daily reserve of one request per active Instrument per scheduled run, and defer-on-exhaustion; verify with concurrent-caller tests against a test Redis that usage never exceeds the budget and backfill cannot take the reserve
- [ ] 3.4 Done when: adapter and rate-limiter tests pass and a CI guard fails any test that opens a connection to the real Tiingo host

## 4. Cleaning gate and reconciliation (feature/market-cleaning-gate; stories 5.1, 5.2)

- [ ] 4.1 Implement the trading-calendar wrapper (XNYS sessions, holidays, close times in UTC, sessions before a date); verify with tests across the March daylight-saving change and on an early-close day
- [ ] 4.2 Implement the ten Cleaning rules as pure `Decimal` functions with severities and the configurable outlier policy (threshold 0.405, skipped on split days); verify one pass and one fail test per rule plus identical and conflicting duplicates and the reject policy
- [ ] 4.3 Implement the Reconciliation report builder (per Instrument and run total; counts per rule, flags, gaps, new Bars, Revisions) and Ruleset version `2026.10.1`; verify the property test received = passed untouched + corrected + duplicates removed + rejected and the property test that no published Bar has a price at or below 0 or high below low
- [ ] 4.4 Done when: every rule, calendar and property test passes and a test asserts gate inputs and outputs contain no floats

## 5. Symbol directory (feature/market-symbol-directory; stories 3.4, 3.5; Could, cut first)

- [ ] 5.1 Schema change: write Alembic revision `0002_symbol_directory` (directory entries and fetch time) and matching models; verify `ci/scripts/migration-check.sh market` passes up, down, up with `0001` and `0002`, and the model-matches-migration test passes
- [ ] 5.2 Implement download and parsing of `nasdaqlisted.txt` and `otherlisted.txt` (trailer skipped, exchange code to MIC, ETF and test-issue fields, normalized share-class matching); verify with stored fixture files
- [ ] 5.3 Add validation to Instrument add: exchange set or confirmed, `etf` suggested, HTTP 422 `test_issue`, `not_listed`, `exchange_mismatch` with override reasons recorded in the Audit entry, `stale_directory` warning past 3 days, HTTP 503 `directory_unavailable` with no copy, 5 s timeout fallback; verify an API test per outcome
- [ ] 5.4 Implement the refresh command that marks active Instruments missing from the directory as `delisted_candidate` (never retired), logs failures and exposes directory age as a metric; verify with success, failure and missing-Instrument tests
- [ ] 5.5 Done when: all directory tests pass with no live download in tests

## 6. Run queue and worker (feature/market-pipeline; story 4.3)

- [ ] 6.1 Implement run creation and the worker claim with `FOR UPDATE SKIP LOCKED` under an advisory lock, crash recovery (reset to pending and re-run), run and Run item recording (mode, status, window, requester, Ruleset version, times, error, counts); verify database tests that two workers never execute one run and a crashed run is recovered
- [ ] 6.2 Implement per-Instrument fetch and staging in `staging_bar`, the circuit (5 consecutive transient failures defer the rest, `partially_succeeded` naming them), `vendor_auth` ending the run `failed`, budget-exhaustion deferral, unknown symbol failing only its Run item, `malformed_response`, and deferral counts; verify a database test per case using the fixture source
- [ ] 6.3 Done when: worker database tests pass in CI

## 7. Publication, Revisions and Data gaps (feature/market-publishing; story 5.3)

- [ ] 7.1 Wire the Cleaning gate into the per-Instrument transaction: publish new Sessions, skip identical content by hash, create Revisions with `bar_revision` and `bar.corrected`, store failed corrections as Rejected bars, store Rejected bars with all rules and raw payload; verify database tests for first insert, identical re-run (zero Bars, Revisions, Events), one changed close (one Revision, one Event, old value readable) and a rejected correction
- [ ] 7.2 Record Data gaps only after close plus 12 hours, never for holidays, resolved on arrival; store the Reconciliation report and Ruleset version on the run and publish `bar.ingested`; verify gap and report-storage database tests
- [ ] 7.3 Verify an interrupted run, re-run, ends with the same Bars, Revisions and Events as an uninterrupted run (database test)
- [ ] 7.4 Done when: publication tests pass and `bar.ingested` and `bar.corrected` schemas are in `contracts/events/`

## 8. Returns and volatility (feature/market-returns; story 6.1)

- [ ] 8.1 Implement log return, adjusted log return and 20- and 60-session annualised volatility (sample standard deviation, undefined until N returns) on `Decimal`; verify against the hand-computed fixture to within 1e-8, plus split-day and dividend-day tests
- [ ] 8.2 Recompute from the earliest new or revised Session using enough history for the 60-session window, store in `return_series`, and include in `bar.ingested`; verify a database test that an old Revision recomputes forward only
- [ ] 8.3 Done when: returns tests pass in CI

## 9. Corporate actions (feature/market-corporate-actions; story 6.2; Could, cut second)

- [ ] 9.1 Record splits (factor above 0) and cash dividends (amount on ex-date) from Vendor data idempotently and serve `adjusted=true` without overwriting raw Bars; verify with recorded split and dividend fixtures ingested twice
- [ ] 9.2 Done when: corporate action tests pass

## 10. Run trigger and scheduler (feature/market-api-and-scheduler; stories 4.4, 4.5)

- [ ] 10.1 Implement `POST /ingestion-runs` (manual and backfill, default start 2015-01-02, default window 5 Sessions before the last Bar to the latest closed Session in America/New_York), HTTP 202 within 800 ms, HTTP 409 with the active run id on overlap, HTTP 403 for non-admins, and a command-line trigger; verify API tests including a timing assertion
- [ ] 10.2 Implement the scheduler process (`daily` 22:30 UTC, `catchup` 06:00 UTC, per-day idempotency keys, enabled by configuration in one Environment only, daily directory refresh when group 5 is merged); verify tests that duplicate firing creates one run and the daily run starts within 15 minutes during a backfill
- [ ] 10.3 Done when: trigger and scheduler tests pass in CI

## 11. Market read API (feature/market-read-api; stories 6.3, 6.4)

- [ ] 11.1 Implement Bars (raw or adjusted, paginated, Session order, decimals as strings, revision, flags, provenance on current and previous revisions) and Return series routes for all signed-in Users; verify API tests including 401 and 404
- [ ] 11.2 Implement run history, run detail with report, Rejected bars, and the data-quality summary (last Session, Bar count, open gaps, flagged Bars, deferral counts, `delisted_candidate`, `stale_directory`, planted Instruments excluded) for admin, quant and analyst; verify API tests including viewer 403 on each route
- [ ] 11.3 Export the OpenAPI document in CI and generate the frontend typed client from it; verify the pipeline publishes the document and a renamed field breaks the frontend type check
- [ ] 11.4 Done when: read API tests and the role matrix pass

## 12. Replay sessions and tick schema (feature/market-replay; stories 7.1, 7.2)

- [ ] 12.1 Implement Replay session create (admin, quant) and read (all signed-in) with 1 to 100 existing Instruments, end after start, speed in (0, 1000]; verify API tests for success, HTTP 422 for each invalid input including the inverted window, and 403 for analyst and viewer
- [ ] 12.2 Publish the versioned tick Event schema under `contracts/events/`; verify a test that valid samples pass and invalid samples fail
- [ ] 12.3 Done when: replay and schema tests pass

## 13. Observability (feature/market-observability; story 6.5)

- [ ] 13.1 Bind run id, Instrument and Vendor to every ingestion log line and redact the API key; verify a test that captures logs from a failing run and asserts the fields and the absence of the key
- [ ] 13.2 Add metrics for runs by status and duration, Bars by outcome, rejections by rule, Vendor calls by status and latency, budget waits, circuit state and outbox backlog; verify a test that each metric name is exposed after a fixture run
- [ ] 13.3 Done when: observability tests pass

## 14. Deployment (feature/market-deployment; story 8.1)

- [ ] 14.1 Add the Dockerfile, compose entries `market`, `market-worker`, `market-scheduler` (enabled on TEST only), `market-relay`, `market-migrate`, the `ci/components.conf` entry, and `TIINGO_API_KEY` and `MARKET_DB_PASSWORD` in the SOPS files; verify the pull request check runs the market lint, format, type check, tests and migration check
- [ ] 14.2 Write the service README and runbook (re-run a window, backfill an Instrument, retire a delisted symbol, read a run report); verify each documented command runs on DEV
- [ ] 14.3 Verify on DEV and TEST: Smoke test on `/api/market/health` reports the deployed Content hash, a forced migration failure leaves the previous version running and fails the build, a token of a User deactivated in the Platform is refused by market within 5 seconds, and the key appears in no Image or log
- [ ] 14.4 Done when: `market` is green in DEV and TEST with `quantsim/test-verified`

## 15. Planted faults and demo evidence (feature/market-planted-faults; stories 8.2, 8.3)

- [ ] 15.1 Build the Planted-fault dataset (bad OHLC order, negative price, weekend date, identical and conflicting duplicates, a 60% jump, zero volume, a missing Session) for dedicated planted Instruments and its stored expected report; verify the CI test that the produced report equals the expected report field for field and a re-run adds zero Bars and Events
- [ ] 15.2 Run the planted-fault window through the fixture source on DEV and TEST and a real-key run on 3 symbols on DEV; verify the report matches exactly on both and real Bars, report and Events land in DEV
- [ ] 15.3 Write the demo spine script (sign in, add three Instruments, trigger, report, re-run zero, viewer 403, inverted replay 422); verify it passes twice in a row at the rehearsal on a fresh TEST deploy
- [ ] 15.4 Done when: SM-1 and SM-2 hold

## Workflow follow-up

- Measure NFR-PERF-002 (200 sequential one-year reads on TEST through the gateway, p95 at most 800 ms) and NFR-PERF-003 (audit trigger overhead on `instrument` inserts) and record them in the Mid report (story 8.4, branch `feature/mid-evidence`).
- Update I1-23 and I1-26 wording in `docs/iteration-plan.md`, and the `NUMERIC(20,6)` and close-plus-one-hour statements in `docs/ingestion-plan.md`.
- Archive the change after review and after the tasks above are complete.
