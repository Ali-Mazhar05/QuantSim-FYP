# Design: add-market-ingestion

## Context

See `proposal.md` for motivation. The market service is the first data service after the Platform. It builds on `libs/qs_template` (local JWT verification, declared Roles per route, append-only audit trigger, transactional outbox with idempotent consumers, structured logging), which is built but unmerged on `feature/service-template`, and on the platform service (`feature/platform-service`, tests pending). The delivery pipeline already builds, deploys and promotes Components listed in `ci/components.conf`. Draft market code exists but is unreviewed (decision D9: split into branches and reviewed).

Binding constraints: free services only; prices are fixed-precision decimals end to end (SPEC NFR-INT-001); schema from migrations only under the migration protocol (PRD addendum section B); the market service owns `market_db` exclusively (SPEC NFR-MNT-002, NFR-SEC-007).

## Goals / Non-Goals

**Goals:**
- One image whose processes always run the same version.
- Exactly-once observable effects (Bars, Revisions, Events) under re-runs, crashes and duplicate scheduling.
- Deterministic Cleaning gate output, so the Planted-fault report can be compared field for field.
- No test and no demo step depends on the live Vendor.

**Non-Goals:**
- High throughput: 40 Instruments of daily Bars is small; the design favours correctness and readability over speed.
- Horizontal scaling of workers beyond "a second worker waits".
- A schema registry: Event schemas live in `contracts/events/` for Iteration 1.

## Decisions

### Service shape: one image, four processes (addendum C)
The container starts as `serve` (FastAPI), `scheduler`, `worker` or `relay` (outbox to Redpanda); a one-off `market-migrate` container runs Alembic before each deploy. *Alternative:* separate images per process; rejected because versions could drift between processes and the pipeline builds one image per Component.

### Job queue in PostgreSQL, not Celery (D6; supersedes I1-26)
A run is a row in `ingestion_run`. The API and scheduler insert rows; the worker claims with `FOR UPDATE SKIP LOCKED` under a PostgreSQL advisory lock, so only one worker executes at a time and a crashed worker's lock is released with its connection; the next worker resets the run to `pending` and re-runs it. Scheduled runs carry a per-day `idempotency_key` (unique), so two schedulers cannot create two `daily` runs. *Alternatives:* Celery or Arq (ARC allows either); rejected for ingestion because they add a broker, cannot express "one daily run per date" without extra state, and the overlap check (HTTP 409) needs the run table anyway. Celery remains an option for Iteration 2 compute jobs.

### Per-Instrument transaction
For each Instrument the worker fetches, stages raw records in `staging_bar`, cleans, publishes, records quality (Rejected bars, Data gaps, Corporate actions), recomputes returns and writes outbox Events in one database transaction. An interruption therefore leaves whole Instruments done or not done, which is what makes the interrupted-run scenario equal an uninterrupted one.

### Publication by content hash, corrections as Revisions (D2)
Each Bar stores a `content_hash` of its normalized values. Same hash: no write, no Event. Different hash that passes the gate: the old values go to `bar_revision`, `revision` increments, `bar.corrected` is published. A correction that fails the gate goes to `rejected_bar` and the Bar is untouched. *Alternative:* silent overwrite (upsert); rejected because quants need "same query, same answer unless a recorded revision explains it".

### Cleaning in pure Python with Decimal (D7; supersedes I1-23)
Each Cleaning rule is a small pure function over `Decimal` values returning zero or more rule hits; the gate composes them and builds the Reconciliation report in the same pass so the identity received = passed untouched + corrected + duplicates removed + rejected holds by construction and is property-tested. *Alternatives:* polars plus pandera; rejected because they introduce binary floats and dataframe semantics for ten simple rules.

### Outliers flagged, configurable to reject (D4)
Threshold: absolute log return above 0.405 (about 50%), skipped on split days. Default `flag`, setting `reject`. Rejecting by default without a second Vendor would discard real moves.

### Trading calendar from `exchange_calendars` (addendum C)
XNYS for all Iteration 1 Instruments (Nasdaq follows the same sessions). Used only for sessions, holidays and close times; prices never pass through pandas. Bar timestamps are the Session close in UTC. A Session counts as expected (can be a Data gap) only after close plus 12 hours, so the 06:00 UTC catch-up run is the first to judge it (PRD FR-25; supersedes the ingestion plan's "close plus one hour").

### Numeric precision (D1, decided 2026-10-10)
Prices and adjusted prices `NUMERIC(23,8)`, volume `NUMERIC(28,8)`, matching ARC section 8.9. API output serializes decimals as strings to avoid float conversion in clients. Database CHECK constraints refuse non-positive prices, `low > high`, open or close outside [low, high], and negative volume.

### Vendor access: Tiingo with a shared Redis budget (addendum C)
Adapter behind a source interface: 30 s timeout, up to 4 attempts with exponential backoff and jitter on timeouts, 5xx and 429 (honouring `Retry-After`); 401 or 403 raises `vendor_auth`; unknown symbols raise without retry. The hourly budget (default 45, `QS_TIINGO_REQUESTS_PER_HOUR`) is a Redis counter keyed by API key and hour, shared across workers and Environments; a reserve of one request per active Instrument per scheduled run is held for `daily` and `catchup`. When the budget is exhausted, the caller defers instead of sleeping. The circuit opens after 5 consecutive transient failures within a run. A fixture source serves recorded responses and is selected by configuration; it only feeds Instruments marked as planted.

### Corporate actions: store raw and adjusted (D3)
Splits and dividends from the Tiingo payload are stored in `corporate_action`; raw Bars are never overwritten; adjusted prices are served on `adjusted=true`. Returns use the Vendor-adjusted close, so FR-27 does not depend on FR-28 if FR-28 is cut.

### Symbol directory (addendum D)
`nasdaqlisted.txt` and `otherlisted.txt` are downloaded daily, parsed (trailer line skipped), and stored as the latest copy with its fetch time in a separate revision `0002_symbol_directory`, so the Could-tier feature can be cut without touching `0001`. Exchange codes map to MICs (Nasdaq XNAS, N XNYS, A XASE, P ARCX, Z BATS, V IEXG). Matching uses a normalized share-class form; the Vendor form is kept in `vendor_symbol`. Validation has a 5 s bound and falls back to the last copy.

### Events and contracts
`instrument.created`, `instrument.retired`, `bar.ingested` (range, new and revised counts, gaps, returns) and `bar.corrected` are written to the outbox in the same transaction and published by `relay` to Redpanda (I-D6). Schemas, including the Market environment tick Event, live in `contracts/events/` with a schema version.

### Authorization (I-D7)
Every route declares its Roles through the template; the service verifies JWTs locally against the Platform's public keys and checks the shared Redis revocation list (fail closed). Traefik only routes and rate-limits.

### Branch and pull request order (ingestion plan section 10, refined)
`market-schema` → `market-instruments` → (`market-tiingo-adapter`, `market-cleaning-gate`, `market-symbol-directory` in parallel) → `market-pipeline` → `market-publishing` → (`market-returns`, `market-corporate-actions`) → `market-api-and-scheduler` → `market-read-api` → `market-replay` → `market-observability` → `market-deployment` → `market-planted-faults`. Rows 5 and 6 of the plan are split so each pull request maps to one epic in `docs/bmad/planning-artifacts/epics.md`.

## Risks / Trade-offs

- [Tiingo free limits are third-party reports (PRD Open Question 3)] → confirm on tiingo.com before relying on SM-8; the budget is configurable and the backfill can be cut to 2 years.
- [One Tiingo key shared by a team server may breach the personal licence (Open Question 11)] → if so, each ingesting Environment gets its own key and the budget applies per key; only TEST schedules runs.
- [`exchange_calendars` brings pandas] → confined to calendar lookups; a test asserts gate inputs and outputs are `Decimal`.
- [The whole schema lands in `0001` before every table is used] → accepted for reviewability (one schema pull request); later changes follow the protocol as new revisions.
- [Data-gap judgement waits 12 hours] → gaps appear the next morning, not the same evening; accepted to avoid false gaps from late Vendor publication.
- [Planted fixture data could pollute real metrics] → planted Instruments are marked and excluded from SM-4 and data-quality totals.
- [Platform and template branches are unmerged] → `market-schema` cannot merge until they pass CI; work on adapter and gate can proceed in parallel since they only need the skeleton.

## Migration Plan

1. `db-init` creates the `market` database, the `market` role and the TimescaleDB extension (superuser steps).
2. `market-migrate` runs `alembic upgrade head` as the `market` role before the new version starts; a failure stops the deploy and leaves the previous version running.
3. `0001_market_schema` creates all Iteration 1 tables; `0002_symbol_directory` adds the directory tables. Both have working downgrades and pass `ci/scripts/migration-check.sh market` (up, down, up) locally and in Jenkins.
4. Rollback: redeploy the previous Image; schema changes within a release are backward-compatible, so the previous version runs against the newer schema.

## Open Questions

- API version segment (`/v1/`, PRD Open Question 7): affects only route prefixes; decide before the frontend client is generated.
