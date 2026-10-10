---
title: QuantSim Iteration 1 PRD — Addendum
created: 2026-10-10
updated: 2026-10-10
---

# Addendum to the Iteration 1 PRD

This addendum holds material that belongs downstream (architecture, stories, Mid report) or that supports the PRD without fitting its main narrative. PRD requirement IDs (FR-1…FR-31) are defined in `prd.md`.

## A. Requirement crosswalk

These are the PRD FRs, the SPEC requirements and Mid report draft (MID) requirements and test cases they realize, the iteration-plan tasks that deliver them, and their status on 2026-10-10. Use this table for MID §4.7 (traceability), Table 4 (milestones) and Table 5 (feature status).

| PRD | SPEC | MID | I1 task(s) | Status 2026-10-10 |
|---|---|---|---|---|
| FR-1 PR checks | NFR-MNT-004, NFR-REC-001 | §6.2 (6) | I1-00 | Done for frontend; backend checks on unmerged branches |
| FR-2 Build once, DEV | NFR-MNT-001, -004 | — | I1-00 | Done (DEV verified 2026-10-07) |
| FR-3 Promotion without rebuild | NFR-MNT-001 | — | I1-00 | TEST verified; ACC failed first run (PR #12 open); PROD never run |
| FR-4 Promotion gates | — | — | I1-00, git-flow skill | Statuses posted; `pr.sh promote` check unmerged |
| FR-5 Sign-off and approval | — | — | I1-00 | Built; never exercised end to end |
| FR-6 Rollback | — | — | I1-00 | Verified with a deliberately broken release |
| FR-7 Release tag | — | — | I1-53 | Not started (`main` untouched, no tags) |
| FR-8 Environment isolation | NFR-MNT-002 | — | I1-00 | Verified (DEV and TEST on one host) |
| FR-9 Encrypted secrets | NFR-SEC-003 | §4.5.4 | I1-00 | Mechanism done; only a sample secret per environment |
| FR-10 Centralized Jenkins | — | — | I1-02 | Built on `feature/centralized-jenkins`; server not provisioned |
| FR-11 Turn-taking host | — | — | I1-02 | Built and hand-over tested; unmerged |
| FR-12 Backup | NFR-REC-002 (Ext, partial) | — | I1-02 | Built; unmerged |
| FR-13 Backend Components | NFR-MNT-004, NFR-REC-001 | — | I1-10, I1-15, market branch 7 | Platform wired on an unmerged branch; market not started |
| FR-14 Users and Roles | FR-PLT-001..003, NFR-INT-002, NFR-SEC-004 | §6.2 (5) | I1-16 | Committed on `feature/platform-service`; tests pending |
| FR-15 Sign-in and verification | FR-PLT-004, NFR-SEC-001 | TC-06 | I1-12, I1-16 | Template done (unmerged); platform committed |
| FR-16 Role checks | FR-PLT-005, NFR-SEC-001 | TC-05 | I1-12 | Template done (unmerged) |
| FR-17 Revocation | FR-PLT-002, -003 | — | I1-12, I1-16 | Committed; tests pending |
| FR-18 Audit | FR-PLT-006..008, NFR-AUD-001/002, NFR-INT-005 | — | I1-14 | Template done (unmerged) |
| FR-19 Reliable Events | NFR-REL-007/008, NFR-OBS-003 | — | I1-13 | Template done (unmerged) |
| FR-20 Instrument master | FR-MKT-001 | §6.2 | I1-21 | Draft code only |
| FR-21 Symbol directory | (new; strengthens FR-MKT-001) | — | new task | Not started |
| FR-22 Runs and schedule | FR-MKT-002, NFR-PERF-004 | FR-01, §6.2 (1) | I1-26 | Not started |
| FR-23 Idempotency and Revisions | FR-MKT-002, NFR-REL-005/008 | TC-01 | I1-24 | Draft code only |
| FR-24 Vendor resilience | NFR-PERF-005, NFR-REL-006 | §7.6 | I1-22 | Draft code only |
| FR-25 Cleaning gate | FR-MKT-011 | FR-02, TC-02, TC-03, §6.2 (2) | I1-23 | Draft code only |
| FR-26 Reconciliation report | FR-MKT-011, -002 | FR-02 | I1-23, I1-28 | Draft code only |
| FR-27 Returns and volatility | FR-MKT-003 | — | I1-25 | Draft code only |
| FR-28 Corporate actions | FR-MKT-010 (Ext) | — | I1-20, I1-25 | Draft code only |
| FR-29 Market read API | FR-MKT-001..003, -011, NFR-PERF-002 | FR-03, TC-04, §6.2 (4) | I1-27 | Draft schemas only |
| FR-30 Replay session and interface | FR-MKT-007 (create), -008, -009, NFR-INT-003 | — | I1-30 | Draft schemas only |
| FR-31 Observability | NFR-OBS-002/003 | — | I1-11, market branches | Template logging done; market not started |

These MID requirements are later work and are **not** in Iteration 1: FR-04…FR-06 (simulation, Iteration 2), FR-07…FR-10 (trading, Iteration 2), FR-11…FR-14 (risk, TDA, ML, alerts, Iterations 2–3) and FR-15/16 (visualization, Iterations 2–4).

## B. Migration protocol (binding on every service; from `docs/ingestion-plan.md` §4.2)

1. **Numbered revisions only.** Every schema change is a new numbered Alembic revision (`0001_market_schema`, then `0002_...`). Applied revisions are never edited; fixes go in a new revision.
2. **Working downgrade.** Every revision has a working `downgrade`. `ci/scripts/migration-check.sh <service>` runs upgrade to head, downgrade to base, and upgrade again on an empty database. It must pass locally before pushing, and it runs in Jenkins on every pull request.
3. **Migrations only.** The schema comes from migrations alone: no manual DDL, and no `create_all` outside tests.
4. **Superuser steps in `db-init`.** Superuser-only steps (creating the database, its role and the TimescaleDB extension) live in `db-init`, not in migrations. Migrations run as the service's own role.
5. **Migrate before start.** Migrations run before the new version starts, through a one-off `<service>-migrate` container. A failed migration stops the deploy.
6. **Backward-compatible within a release.** Add columns as nullable or with defaults. Drop or rename them in a later release, once no running version uses them.
7. **Separate data migrations.** Data migrations are separate revisions from schema changes, and they must be idempotent.
8. **Models match migrations.** The models match the migrations exactly; a test compares them.

## C. Technical decisions taken as accepted

**Ingestion plan decisions (D1–D9):**

| # | Decision | Choice |
|---|---|---|
| D1 | Price storage | `NUMERIC(23,8)` (8 decimal places, aligned with ARC §8.9; changed from the plan's `NUMERIC(20,6)` on 2026-10-10), volume `NUMERIC(28,8)` |
| D2 | Vendor corrections | Revisions plus `bar.corrected` |
| D3 | Corporate actions | Store raw and adjusted series (answers ARC §15 open question 6) |
| D4 | Outliers | Flag and publish (configurable to reject) until a second vendor exists |
| D5 | Universe | 40 instruments (30 large-cap equities, 10 ETFs) |
| D6 | Job queue | PostgreSQL queue (`FOR UPDATE SKIP LOCKED` under an advisory lock) instead of Celery for ingestion |
| D7 | Cleaning implementation | Pure Python with `Decimal` instead of polars and pandera |
| D8 | Backfill start | 2015-01-02 |
| D9 | Draft code | Split into the eight market branches and reviewed |

**Iteration plan decisions (named I-D6 to I-D8 here to avoid the number collision):**

| # | Decision | Choice |
|---|---|---|
| I-D6 | Event backbone | Redpanda, which speaks the Kafka protocol and is used in every environment. This satisfies ARC AD-15's "identical broker semantics" |
| I-D7 | Gateway authentication | Each service verifies the JWT locally; Traefik routes and rate-limits only |
| I-D8 | Revocation | 15-minute access tokens plus a shared Redis revocation list fed on deactivation and role change |

**Delivery decisions** (from `docs/ci-cd.md` and the progress log):
- Jenkins was chosen over GitHub Actions and Woodpecker. It runs self-hosted and is configured as code.
- Images are tagged by content hash, built once on `develop` and promoted by retagging.
- DEV and TEST run on Docker Compose behind Traefik on the CI host. ACC and PROD frontends run on Cloudflare Pages.
- Secrets are SOPS + age encrypted dotenv files, one per environment. These replace ARC's HashiCorp Vault for Iteration 1.
- The shared CI host target is an Oracle Cloud Always Free VM (Canada Southeast, Toronto) with Caddy, Let's Encrypt, DuckDNS, GitHub sign-in and nightly backups. The fallback is laptop turn-taking with `host.sh` and a Cloudflare R2 hand-over.

**Market service shape:**
- **Processes:** one image runs four processes: `serve`, `scheduler`, `worker` and `relay`. A one-off `market-migrate` container runs migrations.
- **Stores:** `market_db` on PostgreSQL 17 + TimescaleDB, with `bar` and `return_series` as hypertables. Redis holds the vendor budget and the revocation list. Redpanda carries events.
- **Trading calendar:** the `exchange_calendars` library (XNYS calendar for all Iteration 1 Instruments; Nasdaq follows the same sessions). It is used only for sessions and close times; prices never pass through pandas.
- **Vendor calls:** 30 s timeout and up to 4 attempts. The circuit opens after 5 consecutive failures. The hourly budget defaults to 45 (`QS_TIINGO_REQUESTS_PER_HOUR`).

## D. Symbol directory source (FR-21)

- **Files:** `nasdaqlisted.txt` (Nasdaq listings) and `otherlisted.txt` (other US exchanges), published daily by Nasdaq Trader under its SymDir directory. Both are pipe-delimited with a trailer line ("File Creation Time"), which must be skipped.
- **Fields used:**
  - symbol: `Symbol` in `nasdaqlisted.txt`; `ACT Symbol` or `NASDAQ Symbol` in `otherlisted.txt`
  - `Security Name`
  - `Exchange` (otherlisted only)
  - `ETF`
  - `Test Issue`
- **Exchange codes to MIC:**

  | Code | Exchange | MIC |
  |---|---|---|
  | (nasdaqlisted) | Nasdaq | XNAS |
  | N | NYSE | XNYS |
  | A | NYSE American | XASE |
  | P | NYSE Arca | ARCX |
  | Z | Cboe BZX | BATS |
  | V | IEX | IEXG |

- **Symbol notation:** share-class notation differs between the directory and the Vendor (for example a class B share). Store the vendor form in `vendor_symbol` and match on a normalized form.
- **Licence:** reference data for personal, non-commercial use. Confirm with Nasdaq before any public deployment. Do not scrape the nasdaq.com website API.
- **Not usable as a price source:** Nasdaq Data Link's free WIKI prices have been frozen since 2018, and its equity price products are paid.

## E. Source reconciliation

The inputs disagree in several places. The PRD position is:

| Topic | Conflict | PRD position |
|---|---|---|
| Job queue | I1-26 says Celery; the ingestion plan says a PostgreSQL queue; ARC allows Arq or Celery | PostgreSQL queue (D6). FR-22 requires a 15-minute daily-start bound instead of "low-priority queue". **Update I1-26 wording** |
| Cleaning tooling | I1-23 says pandera; D7 says pure Python | Pure Python with decimals (D7). **Update I1-23 wording** |
| Report formula | I1-23: passed + corrected + rejected; ingestion plan adds duplicates removed | received = passed untouched + corrected + duplicates removed + rejected (FR-26) |
| Outlier policy | Iteration plan: reject unless a second vendor confirms; ingestion plan: flag | Flag, configurable to reject (D4) |
| Price precision | D1 `NUMERIC(20,6)` vs ARC `NUMERIC(23,8)` | `NUMERIC(23,8)` (decided 2026-10-10) |
| Broker | ARC: Apache Kafka plus schema registry; plans: Redpanda | Redpanda (Kafka protocol, all environments). No schema registry in Iteration 1; schemas live in `contracts/events/` |
| PostgreSQL version | ARC 16; plans 17 | 17 + TimescaleDB |
| Secrets, cold storage, IaC | ARC: Vault, MinIO, Terraform | SOPS + age; R2 or SeaweedFS later; CI host bootstrap script. Record as design evolution (MID §5.5) |
| Orchestration | ARC: Kubernetes in prod | Compose now; k3s considered for Iteration 4 |
| Gateway authentication | ARC: gateway verifies JWT | Each service verifies (I-D7); gateway routes only |
| Tracing | ARC: mandatory; plan: stretch | Deferred (PRD §5, Open Question 8) |
| Correlation | Iteration scope lists it; I1-29 marks it stretch | Stretch; otherwise Iteration 3 |
| Corporate actions | Iteration plan: Extended in Iteration 4; ingestion plan: cheap now | Included (FR-28) |
| Planted-fault location | I1-28: TEST; ingestion branch 8: DEV | Both (SM-2) |
| CI tool in MID | MID Table 5: "GitHub Testing" | Jenkins (PRD FR-1 note) |
| MID performance NFR | "defined using measured results" | SPEC targets, measured on TEST (PRD §5) |
| Test counts | Ingestion plan: 77 and 34 passing; progress log: 75 and "tests pending" | Treat platform tests as unverified until the branch passes CI |

## F. Mid report fill-ins this PRD supports

| MID section | What to put there |
|---|---|
| §3.7 Table 4 | Milestones from crosswalk A, with dates from the progress log (CI/CD 2026-10-06/07; template 2026-10-07; platform 2026-10-09, pending tests) |
| §4.4.1 | Keep FR-01…03 and cite SPEC FR-MKT-001/002/003/011 alongside. Add instrument master and Symbol directory validation |
| §4.5 | Replace the generic NFR text with PRD §5 targets |
| §6.5 Table 5 | Status column from crosswalk A. Change the CI row to Jenkins with evidence "Jenkins build history, commit statuses, PRs #1–#11" |
| §6.8 Table 6 | Jenkins 2.580.1 LTS, Docker Compose, Traefik v3.6, PostgreSQL 17 + TimescaleDB 2.22.1, Redis 8.2, Redpanda v25.2.9, Python 3.12, FastAPI, SQLAlchemy 2 async, Alembic, uv, React + TypeScript, Vitest, SOPS 3.13.3, Cloudflare Pages |
| §7.3 Table 7 | TC-01 → FR-23, TC-02 → FR-25 (duplicates), TC-03 → FR-25, TC-04 → FR-29, TC-05 → FR-16, TC-06 → FR-15. Add TCs for the re-run (zero rows), the planted-fault exact match and the inverted replay window |
| §8.3 Table 8 | Owners from the iteration plan (A platform and CI/CD, B market data, C frontend and schemas). Names to be filled by the team |
