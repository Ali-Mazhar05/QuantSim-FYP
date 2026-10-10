# Proposal: Add market data ingestion (M1), Iteration 1

## Why

Every later QuantSim module (simulator, trading, risk, TDA, ML, dashboard) consumes market data and is only as trustworthy as that data. Iteration 1 must deliver an ingestion engine that turns free end-of-day Vendor data into clean, exact, auditable price history, and the FYP-1 Mid evaluation (Mid-I) demonstrates it: planted bad data rejected with reasons, a re-run adding nothing. Source: approved Iteration 1 PRD (`docs/bmad/planning-artifacts/prds/prd-QuantSim-2026-10-10/prd.md`, section 4.3) and its addendum.

## What Changes

- New `market` service (one image, processes `serve`, `scheduler`, `worker`, `relay`, plus `market-migrate`) built on `libs/qs_template`, owning `market_db` (PostgreSQL 17 + TimescaleDB) exclusively.
- Instrument master: admins add, annotate and retire Instruments; a seed loads the 40-Instrument universe; symbols are validated against the Nasdaq Trader Symbol directory (PRD FR-20, FR-21; SPEC FR-MKT-001, FR-PLT-006).
- Ingestion runs: `daily` (22:30 UTC) and `catchup` (06:00 UTC) schedules plus admin `manual` and `backfill` runs, executed from a PostgreSQL job queue by one worker at a time (PRD FR-22; SPEC FR-MKT-002, NFR-PERF-004).
- Resilient Vendor access to Tiingo: 30 s timeout, retries with backoff, a shared hourly Vendor budget, a circuit that defers instead of hanging, and a fixture Vendor for recorded responses (PRD FR-24; SPEC NFR-PERF-005, NFR-REL-006).
- Cleaning gate with ten named Cleaning rules, Rejected bars kept with reasons, Data gaps, UTC session-close timestamps and a stored Ruleset version (PRD FR-25; SPEC FR-MKT-011).
- Idempotent publication with Revisions and `bar.corrected`, and a Reconciliation report that always adds up (PRD FR-23, FR-26; SPEC FR-MKT-002, FR-MKT-011, NFR-REL-005, NFR-REL-008).
- Return series (log, adjusted log, 20- and 60-session volatility) and Corporate actions with raw and adjusted series (PRD FR-27, FR-28; SPEC FR-MKT-003, FR-MKT-010).
- Market read API for Instruments, Bars, returns, run history, Rejected bars and data quality (PRD FR-29; SPEC FR-MKT-001..003, FR-MKT-011, NFR-PERF-002, NFR-MNT-005 partial).
- Replay session creation and the published tick Event schema of the Market environment interface (PRD FR-30; SPEC FR-MKT-007 create, FR-MKT-008, FR-MKT-009 partial, NFR-INT-003).
- Structured logs, metrics, health and ready endpoints (PRD FR-31; SPEC NFR-OBS-002, NFR-OBS-003).
- Deployment as a pipeline Component with migrate-before-start, and the Planted-fault dataset with its exact expected report (PRD FR-13 market part, SM-2).
- Cross-cutting NFRs honoured: NFR-INT-001 (8-decimal fixed precision: prices `NUMERIC(23,8)`, volume `NUMERIC(28,8)`), NFR-REC-001 (schema from migrations only, addendum section B), NFR-MNT-002 and NFR-SEC-007 (database per service), NFR-SEC-001 (role checks in the owning service), NFR-SEC-003 (no secrets in source or Images), NFR-AUD-001/002 (Instruments audited), NFR-REL-007 (outbox).

## Capabilities

### New Capabilities

- `market-instruments`: the Instrument master, its seed universe and Symbol directory validation (FR-20, FR-21).
- `market-ingestion`: Ingestion run scheduling, triggering, execution, Vendor resilience, idempotent publication with Revisions, and ingestion observability (FR-22, FR-23, FR-24, FR-31).
- `market-cleaning`: the Cleaning gate, Rejected bars, Data gaps and the Reconciliation report (FR-25, FR-26).
- `market-returns`: the Return series and Corporate actions with raw and adjusted prices (FR-27, FR-28).
- `market-read-api`: read access to Instruments, Bars, returns, run history, Rejected bars and data quality (FR-29).
- `market-replay`: Replay session creation and the Market environment tick Event schema (FR-30).

### Modified Capabilities

None. No main specs exist yet under `openspec/specs/`. Platform identity, audit, outbox (FR-14 to FR-19) and the delivery pipeline (FR-1 to FR-13) are prerequisites delivered outside this change.

## Out of Scope

- Rolling correlation series (SPEC FR-MKT-004): stretch in Iteration 1, otherwise Iteration 3 with TDA.
- News ingestion (SPEC FR-MKT-006): Iteration 2.
- Replay playback, pause, speed change and tick streaming (SPEC FR-MKT-007 play), and the portfolio binding operations of FR-MKT-009: Iteration 2 with the simulator.
- Versioned baskets (SPEC FR-MKT-005): Extended, later iteration.
- A second Vendor or cross-vendor outlier confirmation: not in Iteration 1.
- Re-activating a retired Instrument: not in Iteration 1.
- End-to-end tracing (NFR-OBS-001), TLS on internal hops (NFR-SEC-002), audit-index Events (NFR-AUD-003): deferred Core NFRs (Iterations 2 and 4).
- Market service on ACC and PROD: only once a backend server exists (PRD section 8.2); the Mid demo runs on TEST.
- Frontend pages: specified in the iteration-plan frontend tasks, not here.

Iteration: 1 (Sep to Oct 2026, gate Mid-I). If time runs short, cut in PRD section 8.1 order: Symbol directory (FR-21), Corporate actions (FR-28), full backfill and the `catchup` run, the full metrics list, then backend on ACC and PROD.

## Impact

- New code: `services/market/` (service, Alembic migrations `0001_market_schema` and `0002_symbol_directory`, tests), `contracts/events/` (market Event and tick schemas).
- Deployment: `deploy/compose` entries `market`, `market-worker`, `market-scheduler`, `market-relay`, `market-migrate`; `db-init` gains the `market` database, role and TimescaleDB extension; `ci/components.conf` gains `market`; SOPS files gain `TIINGO_API_KEY` and `MARKET_DB_PASSWORD`.
- Dependencies: `exchange_calendars` (sessions and close times only), an async HTTP client for Tiingo; Redis (Vendor budget, revocation list) and Redpanda (Events) already in the stack.
- External: Tiingo free tier (non-commercial licence; free limits to confirm, PRD Open Question 3) and the Nasdaq Trader Symbol directory files (non-commercial reference use).
- Docs to update: I1-23 and I1-26 wording in `docs/iteration-plan.md` (pure Python cleaning, PostgreSQL queue); the `NUMERIC(20,6)` and "close plus one hour" statements in `docs/ingestion-plan.md` sections 4.1 and 6 are superseded by this change.
