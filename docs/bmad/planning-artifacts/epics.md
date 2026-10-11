---
status: draft
stepsCompleted: [1, 2, 3, 4]
mode: non-interactive (requirements confirmed by the team through the approved PRD)
created: 2026-10-10
iteration: 1 (gate Mid-I)
inputDocuments:
  - docs/bmad/planning-artifacts/prds/prd-QuantSim-2026-10-10/prd.md
  - docs/bmad/planning-artifacts/prds/prd-QuantSim-2026-10-10/addendum.md
  - docs/ingestion-plan.md (branch feature/iteration-plan, section 10 work breakdown)
decisions:
  - Prices NUMERIC(23,8), volume NUMERIC(28,8) (addendum D1, PRD Open Question 2)
  - Priority tiers as in PRD section 8.1 (accepted 2026-10-10)
  - No owners assigned yet; no dates (the team owns the schedule)
---

# QuantSim Iteration 1 - Epic Breakdown

## Overview

This document breaks the Iteration 1 PRD (delivery pipeline, platform foundation, market data ingestion engine M1) into epics and stories that the team builds from and that the Mid report traces to. Every story cites the PRD FR ids (FR-1 to FR-31) and the SPEC ids they realize. Acceptance criteria are copied from the PRD "Consequences (testable)" lists, including the failure cases, and are written as Given/When/Then.

Conventions used in every story:

- **Requirements:** PRD FR ids, then SPEC ids (and MID ids or test cases where the addendum crosswalk names them).
- **Priority:** the PRD section 8.1 tier of the FR. Where a story carries a Could item from the 8.1 cut list it says which one.
- **Status:** the 2026-10-10 status from addendum section A. "Draft code only" means unreviewed draft code exists and must be split into the market branches (decision D9).
- **Owner:** blank until the team assigns owners (PRD Open Question 10).
- **Branch:** the `feature/*` branch that delivers the story through one pull request into `develop`. Market branches follow `docs/ingestion-plan.md` section 10; where that plan bundles work that falls into different epics, the bundle is split and the new branch is marked *(new)*. Several stories in the same epic may share one branch (one pull request).
- **Done when:** the condition that closes the story, in addition to every acceptance criterion passing.

**UI contract.** The POC frontend (`frontend/` on `develop`, identical to `develop-poc`) is the single source of truth for every screen (PRD Conventions, "The POC is the UI contract"). No story adds a screen, field, column or control. A story that serves a POC page shapes its API to that page's types; wiring a POC page to the real API replaces its mock data only. A capability with no POC screen is API-only, used through the service's interactive API docs at `/api/<service>/docs`. Addendum section G maps each POC page to its API.

## Requirements Inventory

### Functional Requirements

Delivery pipeline (PRD section 4.1)

- FR-1: Pull request checks. Automated pass/fail on every pull request into `develop` and every feature, bugfix and hotfix branch: pipeline-script lint, frontend lint, type check, tests with coverage, build; per backend Component lint, format, type check, tests and the migration check. *(SPEC NFR-MNT-004, NFR-REC-001; MID section 6.2 item 6)*
- FR-2: Build once, deploy DEV automatically. Merging into `develop` builds an Image only for Components whose Content hash has no Image, deploys DEV, smoke tests, posts `quantsim/dev-verified`. *(SPEC NFR-MNT-001, NFR-MNT-004)*
- FR-3: Promotion without rebuild. Promotion pull requests deploy to TEST, ACC or PROD the exact Images verified in the previous Environment. *(SPEC NFR-MNT-001)*
- FR-4: Promotion gates. A Promotion pull request merges only when the previous Environment's Commit status is green.
- FR-5: Acceptance sign-off and production approval by a Pipeline approver within 24 hours.
- FR-6: Automatic rollback on ACC and PROD when deploy or Smoke test fails; manual Rollback by a Pipeline approver.
- FR-7: Release tagging. A successful PROD deploy tags every Image and the commit with `v<VERSION>`.
- FR-8: Environment isolation. DEV and TEST share a host without affecting each other. *(SPEC NFR-MNT-002)*
- FR-9: Encrypted per-Environment secrets, decrypted only by the pipeline at deploy time. *(SPEC NFR-SEC-003; MID section 4.5.4)*
- FR-10: Team access to a centralized Jenkins at one HTTPS address with GitHub sign-in; anonymous visitors refused.
- FR-11: Turn-taking Jenkins host with state hand-over through free cloud storage and a Host lease.
- FR-12: Jenkins backup, nightly, last 14 kept. *(SPEC NFR-REC-002, Extended, partial)*
- FR-13: Backend Components join the pipeline with one Component entry, including migrate-before-start. *(SPEC NFR-MNT-004, NFR-REC-001; addendum section B)*

Platform foundation (PRD section 4.2)

- FR-14: User accounts and Roles; create, deactivate, reactivate, change Role; nothing deleted. *(SPEC FR-PLT-001, FR-PLT-002, FR-PLT-003; NFR-INT-002, NFR-SEC-004; MID section 6.2 item 5)*
- FR-15: Sign-in and local token verification; 15-minute Access tokens. *(SPEC FR-PLT-004; NFR-SEC-001, NFR-REL-006; MID TC-06)*
- FR-16: Role checks on every route, decided by the owning service. *(SPEC FR-PLT-005; NFR-SEC-001; MID TC-05, TC-06)*
- FR-17: Revocation of previously issued tokens on deactivation or Role change. *(SPEC FR-PLT-002, FR-PLT-003)*
- FR-18: Append-only Audit trail on Users and Instruments. *(SPEC FR-PLT-006, FR-PLT-007, FR-PLT-008; NFR-AUD-001, NFR-AUD-002, NFR-INT-005)*
- FR-19: Reliable Events through a transactional outbox and idempotent consumers. *(SPEC NFR-REL-007, NFR-REL-008; NFR-OBS-003)*

Market data ingestion engine M1 (PRD section 4.3)

- FR-20: Instrument master (symbol, name, sector, listing exchange, currency, asset class, optional Vendor symbol, notes): add, annotate, retire (API-only; the POC Instruments page is read-only), list; seed universe of 40. *(SPEC FR-MKT-001; FR-PLT-006)*
- FR-21: Instrument validation against the Nasdaq Trader Symbol directory, refreshed daily. *(new; strengthens SPEC FR-MKT-001)*
- FR-22: Scheduled (`daily` 22:30 UTC, `catchup` 06:00 UTC) and on-demand (`manual`, `backfill`) Ingestion runs. *(SPEC FR-MKT-002; NFR-PERF-004; MID FR-01)*
- FR-23: Idempotent ingestion with Revisions and `bar.corrected`. *(SPEC FR-MKT-002; NFR-REL-005, NFR-REL-008; MID TC-01)*
- FR-24: Resilient Vendor access: timeout, shared Vendor budget, retry with backoff, circuit, deferral, fixture Vendor. *(SPEC NFR-PERF-005, NFR-REL-006; MID section 7.6)*
- FR-25: Cleaning gate with ten Cleaning rules, UTC session-close timestamps, Rejected bars, Data gaps, Ruleset version. *(SPEC FR-MKT-011; MID FR-02, TC-02, TC-03)*
- FR-26: Reconciliation report per run and per Instrument; received = passed untouched + corrected + duplicates removed + rejected. *(SPEC FR-MKT-011, FR-MKT-002; MID FR-02)*
- FR-27: Returns and volatility (log, adjusted log, 20- and 60-session annualised volatility). *(SPEC FR-MKT-003)*
- FR-28: Corporate actions and adjusted prices; raw and adjusted series kept. *(SPEC FR-MKT-010, Extended)*
- FR-29: Market read API: Instruments (symbol, name, sector, price, change_pct, as the POC Instruments page shows), Bars, Return series for all signed-in Users; run history, run detail, Rejected bars, data quality for admin, quant, analyst (API-only); one Audit Log event per finished Ingestion run. *(SPEC FR-MKT-001..003, FR-MKT-011; NFR-PERF-002; MID FR-03, TC-04)*
- FR-30: Market environments shaped like the POC (name, type `Historical Replay` or `Synthetic Market`, universe, Instruments, start and end date, frequency `Daily`, `Hourly` or `Tick`, status `Draft`, `Ready` or `Active`): create, list, read; and the Market environment interface (tick Event schema). *(SPEC FR-MKT-007 create, FR-MKT-008, FR-MKT-009 partial; NFR-INT-003)*
- FR-31: Market data observability: structured logs, metrics, health and ready. *(SPEC NFR-OBS-002, NFR-OBS-003)*

### NonFunctional Requirements

Cross-cutting (PRD section 5)

- NFR-PERF-002: Standard API operations within 800 ms at p95; measured on TEST through the gateway for market reads and platform user operations.
- NFR-PERF-003: Audit triggers add at most 20% write latency; measured once on `instrument` inserts.
- NFR-PERF-004: Job submission acknowledged within 800 ms (FR-22).
- NFR-PERF-005: Every synchronous dependency call has a timeout (FR-24, JWKS fetch timeouts).
- NFR-REL-005, NFR-REL-007, NFR-REL-008: Idempotent, reclaimable jobs; atomic commit-and-publish; idempotent consumers (FR-19, FR-23).
- NFR-REL-006: Declared degraded behaviour per dependency: Platform down, tokens still verify; Vendor down, deferral; broker down, outbox backlog.
- NFR-INT-001, NFR-INT-002, NFR-INT-003, NFR-INT-005: Decimals; Role constraint; Market environment window check; append-only audit (FR-14, FR-18, FR-25, FR-30).
- NFR-SEC-001, NFR-SEC-003, NFR-SEC-004, NFR-SEC-007: Authorization in the owning service; no secrets in source or Images; hashed passwords; one database role per service (FR-9, FR-14, FR-16).
- NFR-AUD-001, NFR-AUD-002: Audit coverage and history reconstruction (FR-18).
- NFR-OBS-002, NFR-OBS-003: Structured logs and metrics; outbox backlog (FR-19, FR-31).
- NFR-REC-001: Schema from migrations only (FR-13, migration check on every pull request).
- NFR-MNT-001, NFR-MNT-002, NFR-MNT-004, NFR-MNT-006: Same Image everywhere; database per service; per-Component pipeline; shared template (FR-2, FR-3, FR-13).
- NFR-MNT-005 (partial): OpenAPI exported per build; the frontend type check breaks on incompatible changes.

Feature-specific

- NFR-PIPE-FREE: Every service used has a free tier with no card-required paid usage.
- NFR-PIPE-REPRO: The CI host is defined as code (configuration as code, pinned plugins, pinned Jenkins LTS, bootstrap script); a fresh host built from the repository plus secrets runs a green pipeline with no manual configuration.
- NFR-PIPE-LEASTPRIV: The Jenkins controller has no Docker access; builds run on a separate agent.
- NFR-MKT-DECIMAL: Prices and money are fixed-precision decimals with 8 decimal places from Vendor response to API output (SPEC NFR-INT-001); stored as `NUMERIC(23,8)`, volume `NUMERIC(28,8)`.
- NFR-MKT-MIGRATIONS: `market_db` is built from its own migration history alone; every migration is reversible (SPEC NFR-REC-001; addendum section B).
- NFR-MKT-OWNERSHIP: The market service owns `market_db` exclusively (SPEC NFR-MNT-002, NFR-SEC-007).

Deferred Core NFRs (not delivered in Iteration 1; no stories): NFR-OBS-001 tracing (stretch, else Iteration 2), NFR-SEC-002 TLS on internal hops (Iteration 4), NFR-AUD-003 audit-index Events (Iteration 2).

### Additional Requirements

From the addendum and PRD constraints (no separate architecture document exists for Iteration 1; the addendum carries the accepted technical decisions):

- AR-1 Migration protocol (addendum section B), binding on every service: numbered Alembic revisions only, never edited once applied; working downgrade checked by `ci/scripts/migration-check.sh <service>` (up, down, up) locally and on every pull request; schema from migrations only; superuser steps in `db-init`; migrate before start through a one-off `<service>-migrate` container, a failed migration stops the deploy; backward-compatible within a release; data migrations separate and idempotent; a test checks that models match migrations.
- AR-2 Market service shape: one image, four processes (`serve`, `scheduler`, `worker`, `relay`) plus `market-migrate`; `market_db` on PostgreSQL 17 + TimescaleDB with `bar` and `return_series` as hypertables; Redis for the Vendor budget and revocation list; Redpanda for Events; event schemas in `contracts/events/` (no schema registry).
- AR-3 Job queue: PostgreSQL queue (`FOR UPDATE SKIP LOCKED` under an advisory lock), not Celery (D6; supersedes I1-26 wording).
- AR-4 Cleaning in pure Python with `Decimal`, not polars or pandera (D7; supersedes I1-23 wording).
- AR-5 Trading calendar: `exchange_calendars` XNYS for sessions and close times only; prices never pass through pandas.
- AR-6 Vendor: Tiingo end-of-day; 30 s timeout, up to 4 attempts, circuit opens after 5 consecutive failures, hourly budget default 45 (`QS_TIINGO_REQUESTS_PER_HOUR`).
- AR-7 Outliers flagged and published, configurable to reject (D4); corrections become Revisions plus `bar.corrected` (D2); raw and adjusted series both stored (D3).
- AR-8 Universe of 40 Instruments (30 large-cap equities, 10 ETFs) (D5); backfill start 2015-01-02 (D8).
- AR-9 Symbol directory source (addendum section D): `nasdaqlisted.txt` and `otherlisted.txt`, pipe-delimited, trailer line skipped; exchange code to MIC mapping; vendor symbol stored in `vendor_symbol`, match on a normalized form; never a price source; do not scrape nasdaq.com.
- AR-10 Event backbone Redpanda in every environment (I-D6); each service verifies JWTs locally, Traefik routes and rate-limits only (I-D7); 15-minute access tokens plus a shared Redis revocation list (I-D8).
- AR-11 Delivery: Jenkins self-hosted, images tagged by content hash, built once on `develop`, promoted by retagging; DEV and TEST on Docker Compose behind Traefik; ACC and PROD frontends on Cloudflare Pages; SOPS + age secrets; shared CI host target Oracle Cloud Always Free with Caddy, Let's Encrypt, DuckDNS; fallback laptop turn-taking with `host.sh` and Cloudflare R2.
- AR-12 Process constraints (PRD section 6): `feature/*` to `develop` to `test` to `acceptance` to `main`, one branch per task; one-line commit messages with no punctuation and no AI attribution; `develop-poc` never modified, `master` stays empty; free services only; data licence non-commercial.

### UX Design Requirements

No new UX. The POC frontend is the UI contract (see the UI contract note above and PRD section 7): no screen, field, column or control is added. Iteration 1 wires these POC pages to real APIs, replacing mock data only: sign-in, Instruments, Market Data, Market Environments (list and create), Users, Audit Log and System health (addendum section G). Every other POC page keeps its mock data until its iteration.

### FR Coverage Map

FR-1: Epic 1 (frontend checks); Epic 2 (backend checks, story 2.7)
FR-2: Epic 1
FR-3: Epic 1
FR-4: Epic 1
FR-5: Epic 1
FR-6: Epic 1
FR-7: Epic 1
FR-8: Epic 1
FR-9: Epic 1
FR-10: Epic 1
FR-11: Epic 1
FR-12: Epic 1
FR-13: Epic 2 (platform joins, story 2.7); Epic 8 (market joins, story 8.1)
FR-14: Epic 2
FR-15: Epic 2
FR-16: Epic 2 (mechanism); Epics 3, 4, 6, 7 (market routes)
FR-17: Epic 2
FR-18: Epic 2 (mechanism); Epic 3 (Instruments audited)
FR-19: Epic 2 (mechanism); Epics 3, 5, 6 (market Events)
FR-20: Epic 3
FR-21: Epic 3
FR-22: Epic 4
FR-23: Epic 4 (one worker at a time); Epic 5 (idempotency and Revisions)
FR-24: Epic 4
FR-25: Epic 5
FR-26: Epic 5; Epic 8 (planted-fault exact match)
FR-27: Epic 6
FR-28: Epic 6
FR-29: Epic 6
FR-30: Epic 7
FR-31: Epic 6 (logs, metrics); Epic 3 (health and ready); Epic 8 (smoke on health)

The story-level map is at the end of this document.

## Epic List

### Epic 1: Safe delivery pipeline for every change
Developers get an automated verdict on every pull request and see merged work running in DEV; approvers promote exactly the verified Images through TEST, ACC and PROD with sign-off, rollback and a tagged `v0.1.0` Release; any team member can reach or host Jenkins at no cost.
**FRs covered:** FR-1 (frontend), FR-2, FR-3, FR-4, FR-5, FR-6, FR-7, FR-8, FR-9, FR-10, FR-11, FR-12. FR-13 is delivered by stories 2.7 and 8.1 because it needs a backend Component to exist.

### Epic 2: Signed-in, role-checked and audited platform
Admins control who can do what; every User signs in once and is recognised by every service without a per-request call to the Platform; every change to business data is audited and every state change publishes its Events reliably. The platform service runs through the pipeline.
**FRs covered:** FR-13 (platform), FR-14, FR-15, FR-16, FR-17, FR-18, FR-19, FR-1 (backend checks).

### Epic 3: Trustworthy Instrument master
Admins keep a validated list of tracked Instruments, seeded with the 40-Instrument universe and checked against official exchange listings, with every change audited and published. Changes are API-only; the POC Instruments page lists the result.
**FRs covered:** FR-20, FR-21 (and FR-16, FR-18, FR-19, FR-31 health for the market service).

### Epic 4: Ingestion runs that survive the Vendor
Admins get Ingestion runs every day without babysitting and on demand; runs stay within the shared Vendor budget, retry transient failures, defer instead of hanging when the Vendor is down, and record exactly what happened per Instrument.
**FRs covered:** FR-22, FR-24, FR-23 (single executing worker).

### Epic 5: Cleaning gate, Revisions and reconciliation
Only records that pass the Cleaning gate become Bars; rejected records are kept with their reasons; re-runs add nothing; vendor corrections become visible Revisions; every run's Reconciliation report adds up exactly.
**FRs covered:** FR-25, FR-26, FR-23.

### Epic 6: Returns, corporate actions and the market read API
Quants read exact, session-ordered, optionally adjusted Bars and a single published Return series; the POC Instruments and Market Data pages read the same API; analysts read run history, Rejected bars and data quality through the API; every finished run appears on the POC Audit Log page; operators see failures and staleness through logs and metrics.
**FRs covered:** FR-27, FR-28, FR-29, FR-31.

### Epic 7: Market environments
Admins and quants create validated Market environments shaped exactly like the POC Market Environments pages, and the Market environment interface's tick Event schema is published so Iteration 2 can bind portfolios to replayed or simulated markets.
**FRs covered:** FR-30.

### Epic 8: Mid demo evidence
The market service runs on DEV and TEST through the pipeline; the Planted-fault dataset proves the Cleaning gate field for field; the demo spine and the measured NFR evidence are ready for the Mid-I panel.
**FRs covered:** FR-13 (market), FR-26 and FR-25 (planted-fault proof), FR-24 (fixture Vendor on TEST); success metrics SM-1, SM-2, SM-4, SM-7; NFR-PERF-002, NFR-PERF-003.

Dependency flow: Epic 1 stands alone. Epic 2 uses Epic 1. Epic 3 uses Epic 2 (template, auth, audit, outbox). Epic 4 uses Epic 3. Epic 5 uses Epics 3 and 4. Epic 6 uses Epic 5. Epic 7 uses Epic 3. Epic 8 uses Epics 1 to 7. No epic needs a later epic to function.

## Epic 1: Safe delivery pipeline for every change

Developers and Pipeline approvers ship changes through one Jenkins pipeline: checked on every pull request, built once, promoted unchanged, gated by sign-off and approval, rolled back automatically, tagged on release, and reachable by the whole team on free services. Most of this epic is delivered for the frontend (merged PRs #7 to #11); the open work is the first ACC and PROD Release, team access and hosting.

### Story 1.1: Automated pull request checks for the frontend and pipeline scripts

As a developer,
I want an automated pass or fail on every pull request within minutes,
So that I know my change is safe to review before anyone looks at it.

- **Requirements:** FR-1 (frontend and pipeline-script part); SPEC NFR-MNT-004, NFR-REC-001; MID section 6.2 item 6
- **Priority:** Must
- **Status:** Done for frontend (addendum A). Backend checks are delivered by story 2.7.
- **Owner:**
- **Depends on:** none
- **Branch:** feature/ci-scripts, feature/jenkinsfile (merged, PRs #7 and #10)

**Acceptance Criteria:**

**Given** a pull request into `develop`, or a push to any `feature/*`, `bugfix/*` or `hotfix/*` branch
**When** Jenkins builds it
**Then** Jenkins posts `continuous-integration/jenkins/branch` on the pull request head commit
**And** the check covers pipeline-script linting, frontend lint, type check, tests with coverage and build

**Given** a completed check
**When** a developer opens the Jenkins build page
**Then** the test results (JUnit) and the frontend coverage are published there

**Given** the CI host is online and idle
**When** a developer pushes
**Then** the check result is posted within 15 minutes of the push (measured 2 min 13 s for the frontend-only pipeline)

**Given** a pull request that breaks lint, types, tests or the build
**When** the check runs
**Then** the posted status is failure

**Done when:** every open pull request carries the status, and the measured check time is recorded for SM-5.

### Story 1.2: Build once and deploy DEV on merge

As a developer,
I want every merge into `develop` to build only what changed and deploy it to DEV with a smoke test,
So that I never have to remember manual deploy steps and can see my change running.

- **Requirements:** FR-2; SPEC NFR-MNT-001, NFR-MNT-004
- **Priority:** Must
- **Status:** Done (DEV verified 2026-10-07)
- **Owner:**
- **Depends on:** 1.1
- **Branch:** feature/jenkinsfile, feature/compose-environments (merged, PRs #8 and #10)

**Acceptance Criteria:**

**Given** a merge into `develop` that changes only one Component (for example only the market service)
**When** the pipeline runs
**Then** only that Component's Image is built, and every other Component keeps its existing Image without a rebuild

**Given** a DEV deploy
**When** any Component serves a Content hash different from the one deployed
**Then** the DEV Smoke test fails

**Given** a DEV deploy
**When** the Smoke test fails
**Then** `quantsim/dev-verified` is not posted; it is posted only after a successful DEV Smoke test

**Done when:** a merge shows `quantsim/dev-verified` on the commit and DEV serves the merged Content hash.

### Story 1.3: Promote the verified Images to TEST, ACC and PROD without rebuilding

As a pipeline approver,
I want each Promotion pull request to deploy the exact Images that passed the previous Environment,
So that what reaches ACC and PROD is exactly what passed TEST.

- **Requirements:** FR-3; SPEC NFR-MNT-001
- **Priority:** Must
- **Status:** In progress. TEST verified; ACC failed its first run on a Pages certificate wait (fix in PR #12); PROD never run.
- **Owner:**
- **Depends on:** 1.2
- **Branch:** bugfix/pages-smoke-wait (PR #12, open) for the ACC fix

**Acceptance Criteria:**

**Given** a Promotion pull request whose required Image is missing
**When** it is merged
**Then** the pipeline refuses to deploy with the error "Not built on develop"
**And** it never builds during Promotion

**Given** the same source verified in DEV
**When** it is promoted to TEST, ACC and PROD
**Then** the Content hash served in each Environment equals the one verified in DEV

**Given** a Promotion to TEST
**When** the TEST deploy succeeds
**Then** `quantsim/test-verified` is posted on the commit

**Done when:** PR #12 is merged and ACC serves the Content hash verified in TEST.

### Story 1.4: Isolated DEV and TEST on one host

As a developer,
I want DEV and TEST to run side by side on the CI host without affecting each other,
So that redeploying DEV never breaks the TEST demo.

- **Requirements:** FR-8; SPEC NFR-MNT-002
- **Priority:** Must
- **Status:** Done (verified, DEV and TEST on one host)
- **Owner:**
- **Depends on:** 1.2
- **Branch:** feature/compose-environments (merged, PR #8)

**Acceptance Criteria:**

**Given** DEV and TEST running on the same host
**When** DEV is redeployed
**Then** TEST's containers, data and routes are untouched

**Given** any Environment
**When** its gateway receives a request
**Then** it routes only to that Environment's own Components

**Done when:** verified (no further work).

### Story 1.5: Encrypted per-Environment secrets for every real secret

As a pipeline approver,
I want each Environment's secrets stored encrypted in the repository and decrypted only by the pipeline at deploy time,
So that no database password, signing key or Vendor API key ever leaks through the repository, an Image or a log.

- **Requirements:** FR-9; SPEC NFR-SEC-003; MID section 4.5.4
- **Priority:** Must
- **Status:** Partially done. The SOPS + age mechanism is done; each Environment holds only a sample secret. Open: real secrets (database passwords, signing keys, `TIINGO_API_KEY`, first admin), and git-ignoring the untracked `admin_password` file and `ci/jenkins/.state/` (PRD Open Question 12).
- **Owner:**
- **Depends on:** 1.2
- **Branch:** feature/compose-environments (mechanism, merged); remaining work feature/environment-secrets *(new)*

**Acceptance Criteria:**

**Given** the repository, every Image and every build log
**When** they are searched for secret values
**Then** no plaintext secret is found

**Given** a team member who needs to decrypt
**When** their public key is added and the files are re-encrypted
**Then** they can decrypt, and no secret value changed

**Given** a deploy step
**When** it ends, whether the deploy passed or failed
**Then** the pipeline has deleted the decrypted file

**Given** the working tree
**When** a developer runs `git add .`
**Then** `admin_password` and `ci/jenkins/.state/` are ignored and not staged

**Done when:** DEV and TEST secrets files hold the real secrets the platform and market services need, and the ignore rules are merged.

### Story 1.6: Automatic and manual rollback on ACC and PROD

As a pipeline approver,
I want a failed ACC or PROD deploy to roll back to the previous release on its own, and a manual rollback when I need one,
So that I can undo a bad release without a scramble.

- **Requirements:** FR-6
- **Priority:** Should
- **Status:** Done for automatic rollback (verified with a deliberately broken release). Manual rollback not recorded as verified.
- **Owner:**
- **Depends on:** 1.3
- **Branch:** feature/jenkinsfile (merged, PR #10)

**Acceptance Criteria:**

**Given** a deliberately broken release deployed to ACC
**When** the deploy or the Smoke test fails
**Then** the pipeline redeploys ACC's previously recorded release and smoke tests it
**And** ACC ends serving the previous Content hash and the build is marked failed

**Given** any Environment with a recorded previous release
**When** a Pipeline approver triggers a manual Rollback
**Then** that Environment serves its previous release

**Done when:** a manual Rollback has been exercised once and recorded.

### Story 1.7: Promotion gates on the previous Environment's status

As a pipeline approver,
I want a Promotion pull request to be mergeable only when the previous Environment is green,
So that nothing skips DEV, TEST or acceptance sign-off.

- **Requirements:** FR-4
- **Priority:** Should
- **Status:** Partially done. Statuses are posted; the `pr.sh promote` check is unmerged.
- **Owner:**
- **Depends on:** 1.3
- **Branch:** feature/git-flow-skill

**Acceptance Criteria:**

**Given** Promotion pull requests into `test`, `acceptance` and `main`
**When** they are opened
**Then** the head commit shows `quantsim/dev-verified`, `quantsim/test-verified` and `quantsim/acceptance-signoff` respectively

**Given** a Promotion head commit that lacks its required status
**When** a developer runs `pr.sh promote`
**Then** the script refuses to open the Promotion pull request

**Given** `docs/ci-cd.md`
**When** it is read
**Then** it states the gate rule (GitHub branch protection is unavailable on the free private plan, so convention plus tooling enforce it)

**Done when:** the `pr.sh promote` check is merged and the rule is in `docs/ci-cd.md`.

### Story 1.8: Acceptance sign-off and production approval by Pipeline approvers

As a pipeline approver,
I want ACC to wait for my sign-off and PROD to wait for my approval, each within 24 hours,
So that I decide what reaches acceptance and production.

- **Requirements:** FR-5
- **Priority:** Should
- **Status:** Built; never exercised end to end
- **Owner:**
- **Depends on:** 1.3
- **Branch:** none (exercised on the existing pipeline during story 1.9)

**Acceptance Criteria:**

**Given** a successful ACC deploy
**When** a Pipeline approver accepts or rejects within 24 hours
**Then** the result is posted as `quantsim/acceptance-signoff`

**Given** a merge into `main`
**When** a Pipeline approver approves within 24 hours
**Then** PROD is deployed; it is not deployed before approval

**Given** a team member who is not a Pipeline approver
**When** they try to submit either decision
**Then** they cannot

**Given** a rejection or a 24-hour timeout
**When** the decision step ends
**Then** `quantsim/acceptance-signoff` is posted as failure and the build ends ABORTED

**Given** a build waiting for a decision
**When** the wait is in progress
**Then** no build executor is held

**Done when:** one acceptance sign-off and one production approval have been given end to end.

### Story 1.9: Tag the first Release v0.1.0

As a pipeline approver,
I want a successful PROD deploy to tag every Image and the commit with the version,
So that the Release is recorded and can be rolled back.

- **Requirements:** FR-7; SM-3
- **Priority:** Should
- **Status:** Not started (`main` untouched, no tags)
- **Owner:**
- **Depends on:** 1.3, 1.8
- **Branch:** feature/release-tagging *(new)*

**Acceptance Criteria:**

**Given** a `VERSION` file containing `0.1.0`
**When** the PROD deploy succeeds
**Then** every Image and the git commit are tagged `v0.1.0`

**Given** the tag `v<VERSION>` already exists
**When** a PROD deploy starts
**Then** the pipeline fails before deploying

**Given** the end of Iteration 1
**When** `main` is inspected
**Then** tag `v0.1.0` exists and PROD serves the Content hashes that tag records (at least the frontend; backend on ACC and PROD only if a server exists)

**Done when:** SM-3 holds: `v0.1.0` on `main`, ACC and PROD serve the TEST-verified hash, sign-off posted by a Pipeline approver.

### Story 1.10: Team access to a centralized Jenkins

As a developer,
I want one stable HTTPS address where I sign in to Jenkins with my GitHub account,
So that the whole team can see and use the pipeline without depending on one laptop.

- **Requirements:** FR-10; NFR-PIPE-FREE, NFR-PIPE-REPRO, NFR-PIPE-LEASTPRIV
- **Priority:** Could (FR-10 is not named in a PRD section 8.1 tier; its webhook is Could item 5 and FR-11 is the fallback, so it is treated as Could)
- **Status:** Built on `feature/centralized-jenkins`; Oracle server not provisioned
- **Owner:**
- **Depends on:** 1.2
- **Branch:** feature/centralized-jenkins

**Acceptance Criteria:**

**Given** the Jenkins address
**When** an anonymous visitor requests it
**Then** they get HTTP 403 or a login redirect

**Given** a GitHub account outside the configured team list
**When** it tries to sign in
**Then** sign-in is refused; team accounts map to the Developer or Pipeline approver role

**Given** a push to GitHub
**When** the webhook is configured
**Then** the push triggers a build; without a webhook, Jenkins scans for changes every 5 minutes or less

**Given** a fresh host
**When** it is built from the bootstrap script, configuration as code and a backup restore
**Then** it runs a green pipeline with no manual Jenkins configuration
**And** the controller has no Docker access; builds run on a separate agent

**Done when:** the Oracle Always Free VM serves Jenkins at its DuckDNS address with team sign-in (until then story 1.11 is the operating mode).

### Story 1.11: Turn-taking Jenkins host with hand-over

As a developer,
I want to take over hosting Jenkins on my laptop with the full history restored,
So that the pipeline stays available when the shared server is not.

- **Requirements:** FR-11
- **Priority:** Should
- **Status:** Built and hand-over tested; unmerged
- **Owner:**
- **Depends on:** 1.2
- **Branch:** feature/centralized-jenkins

**Acceptance Criteria:**

**Given** the previous host stopped Jenkins cleanly
**When** a team member starts a host
**Then** the previous host's build history is restored
**And** DEV and TEST are redeployed on the new host and teammates reach them at the new public address

**Given** another host's lease was refreshed less than 10 minutes ago
**When** a team member tries to start a host
**Then** the start is refused until the other host stops or its lease expires

**Done when:** merged into `develop` and one hand-over is recorded.

### Story 1.12: Nightly Jenkins backup

As a pipeline approver,
I want the shared CI host backed up nightly with the last 14 backups kept,
So that a lost host never loses jobs, credentials references or history.

- **Requirements:** FR-12; SPEC NFR-REC-002 (Extended, minimal form)
- **Priority:** Could (cut item 5)
- **Status:** Built; unmerged
- **Owner:**
- **Depends on:** 1.10
- **Branch:** feature/centralized-jenkins

**Acceptance Criteria:**

**Given** the shared CI host
**When** a night passes
**Then** a backup is taken and only the last 14 are kept

**Given** the latest backup
**When** it is restored into a fresh Jenkins
**Then** jobs, credentials references and build history are back

**Done when:** one restore into a fresh Jenkins has been demonstrated.

## Epic 2: Signed-in, role-checked and audited platform

Every service builds on `libs/qs_template`, which verifies Access tokens locally, enforces declared Roles, audits business data and publishes Events through a transactional outbox. The Platform service (M0) owns Users, Roles and sign-in, and joins the pipeline as the first backend Component.

### Story 2.1: Local token verification and declared Roles on every route (service template)

As a developer,
I want the service template to verify Access tokens locally and refuse any route without a Role declaration,
So that every service enforces authorization itself and keeps working when the Platform is down.

- **Requirements:** FR-15 (verification), FR-16; SPEC FR-PLT-004, FR-PLT-005, NFR-SEC-001, NFR-REL-006, NFR-PERF-005 (JWKS fetch timeout); MID TC-05, TC-06
- **Priority:** Must
- **Status:** Template done (unmerged)
- **Owner:**
- **Depends on:** 1.1
- **Branch:** feature/service-template

**Acceptance Criteria:**

**Given** a request with no token
**When** it reaches any route
**Then** it gets HTTP 401

**Given** an expired, forged or wrongly signed token
**When** it is presented
**Then** it is rejected with HTTP 401

**Given** a valid token whose Role is not allowed on the route
**When** it is presented
**Then** it gets HTTP 403

**Given** a service built on the template
**When** the automated route test enumerates every route
**Then** it fails if any route lacks a Role declaration

**Given** the Platform is stopped
**When** an already-issued token is presented to another service before it expires
**Then** it is still accepted (verification uses the Platform's published public keys, fetched with a timeout)

**Done when:** template merged into `develop` with these tests green in CI.

### Story 2.2: Append-only audit trail (service template)

As an admin,
I want every insert, update and delete on audited data recorded with before and after state, the acting User and the request id,
So that I can reconstruct who changed what, even after a row is deleted.

- **Requirements:** FR-18; SPEC FR-PLT-006, FR-PLT-007, FR-PLT-008, NFR-AUD-001, NFR-AUD-002, NFR-INT-005
- **Priority:** Must
- **Status:** Template done (unmerged)
- **Owner:**
- **Depends on:** 2.1
- **Branch:** feature/service-template

**Acceptance Criteria:**

**Given** an audited table
**When** a row is inserted, updated and deleted
**Then** each operation produces exactly one Audit entry with before-state, after-state, acting User and request id

**Given** the audit table
**When** an UPDATE, DELETE or TRUNCATE is run on it, even by the table owner
**Then** it fails

**Given** a deleted audited row
**When** its history is queried
**Then** its Audit entries are still returned

**Given** a column designated secret (for example a password hash)
**When** its row changes
**Then** the column is excluded from the Audit entry

**Done when:** template merged with these tests green.

### Story 2.3: Reliable Events through a transactional outbox (service template)

As a developer,
I want a state change and its Events committed together and delivered even after a broker outage,
So that no Event is ever lost and consuming one twice has no extra effect.

- **Requirements:** FR-19; SPEC NFR-REL-007, NFR-REL-008, NFR-OBS-003
- **Priority:** Must
- **Status:** Template done (unmerged)
- **Owner:**
- **Depends on:** 2.1
- **Branch:** feature/service-template

**Acceptance Criteria:**

**Given** the broker is stopped
**When** writes happen
**Then** the writes succeed and their Events are delivered after the broker returns

**Given** a consumer that already processed an Event
**When** the same Event is replayed to it
**Then** nothing changes

**Given** unpublished Events in the outbox
**When** metrics are scraped
**Then** the outbox backlog is exposed as a metric

**Done when:** template merged with these tests green.

### Story 2.4: Admin manages User accounts and Roles

As an admin,
I want to create Users with a unique username, email and Role, and to deactivate, reactivate and change their Role without deleting anything,
So that I control who can do what.

- **Requirements:** FR-14; SPEC FR-PLT-001, FR-PLT-002, FR-PLT-003, NFR-INT-002, NFR-SEC-004; MID section 6.2 item 5
- **Priority:** Must
- **Status:** Committed on `feature/platform-service`; tests pending
- **Owner:**
- **Depends on:** 2.1, 2.2, 2.3
- **Branch:** feature/platform-service

**Acceptance Criteria:**

**Given** the users table
**When** a Role outside {admin, quant, analyst, viewer} is written
**Then** the database refuses it

**Given** a new password
**When** it is stored
**Then** it is stored only as a salted one-way hash, has at least 12 characters, and never appears in logs or Audit entries

**Given** exactly one active admin
**When** that admin is deactivated or demoted, including by concurrent requests
**Then** the request is refused

**Given** a deactivation, reactivation or Role change
**When** it is committed
**Then** `user.deactivated`, `user.reactivated` or `user.role_changed` is published

**Given** a fresh Environment
**When** it is deployed
**Then** the first admin is created from that Environment's encrypted secrets
**And** deploying again creates no second admin, and no admin password exists in plaintext in the repository or the working tree

**Given** a quant, analyst or viewer User
**When** they call any user-management operation or read audit history
**Then** they get HTTP 403

**Done when:** the platform tests run green in CI (addendum E: platform tests count as unverified until then).

### Story 2.5: Sign in with username and password

As a quant,
I want to sign in once and receive a 15-minute Access token,
So that I can use every service with one identity.

- **Requirements:** FR-15; SPEC FR-PLT-004, NFR-SEC-001; MID TC-06
- **Priority:** Must
- **Status:** Platform committed (tests pending)
- **Owner:**
- **Depends on:** 2.4
- **Branch:** feature/platform-service

**Acceptance Criteria:**

**Given** valid credentials
**When** a User signs in
**Then** they receive an Access token valid for 15 minutes

**Given** a wrong password, an unknown user or a deactivated account
**When** sign-in is attempted
**Then** all three get the same response

**Given** 5 failed attempts
**When** a further sign-in is attempted within 15 minutes
**Then** it is refused with HTTP 429

**Given** a token older than 15 minutes
**When** it is presented
**Then** it is rejected with HTTP 401 and the frontend returns the User to the sign-in page (no refresh tokens or logout in Iteration 1)

**Done when:** tests green in CI.

### Story 2.6: Revoke tokens on deactivation or Role change

As an admin,
I want a deactivated or re-roled User's existing tokens to stop working everywhere,
So that removing access takes effect at once, not after 15 minutes.

- **Requirements:** FR-17; SPEC FR-PLT-002, FR-PLT-003
- **Priority:** Should
- **Status:** Committed; tests pending
- **Owner:**
- **Depends on:** 2.5
- **Branch:** feature/platform-service

**Acceptance Criteria:**

**Given** a token issued before a User was deactivated
**When** it is presented to the market service
**Then** it is refused within 5 seconds of the deactivation

**Given** a token issued before a Role change
**When** it is presented after the change
**Then** it is refused

**Given** the revocation store is unreachable
**When** any token is presented
**Then** services refuse it (fail closed)

**Done when:** tests green in CI; the market-side check is re-verified in story 8.1.

### Story 2.7: Platform service joins the pipeline with backend checks and migrate-before-start

As a developer,
I want a backend service to join the pipeline by adding one Component entry,
So that it gets the same checks, build-once deploys and migration safety as the frontend.

- **Requirements:** FR-13 (platform), FR-1 (backend checks); SPEC NFR-MNT-004, NFR-REC-001, NFR-MNT-006; addendum section B items 2 and 5
- **Priority:** Must (backend on ACC and PROD is Could item 6)
- **Status:** Platform wired on unmerged branch (`ci/components.conf` entry on `feature/platform-service`)
- **Owner:**
- **Depends on:** 1.2, 1.3, 1.5, 2.4
- **Branch:** feature/platform-service

**Acceptance Criteria:**

**Given** a pull request touching a backend Component
**When** the check runs
**Then** it covers lint, format, type check, tests and the migration check for that Component

**Given** a pull request containing a migration whose downgrade fails
**When** the check runs
**Then** the check fails before review starts

**Given** the `platform` Component entry
**When** it is merged
**Then** `platform` passes the pull request checks, deploys to DEV and TEST, and passes a Smoke test on `/api/platform/health` that reports the deployed Content hash

**Given** a deploy whose `platform-migrate` step fails
**When** the deploy runs
**Then** the previous version keeps running and the build is marked failed

**Done when:** `platform` is green in DEV and TEST with `quantsim/test-verified`.

## Epic 3: Trustworthy Instrument master

Admins maintain the Instrument master in the market service: add, annotate, retire and list Instruments, seed the 40-Instrument universe, and validate symbols against the Nasdaq Trader Symbol directory. Adding, annotating and retiring are API-only (addendum section G); the POC Instruments page stays read-only. The market schema is its own story (addendum section B).

### Story 3.1: Market service skeleton and schema 0001_market_schema

As a developer,
I want the market service skeleton and its first numbered, reversible migration,
So that every later market story builds on a database that comes from migrations alone and refuses impossible data.

- **Requirements:** enables FR-20 to FR-30; FR-25 (database refuses bad Bars), FR-30 (database refuses an inverted Market environment window and values outside the POC's type, frequency and status), FR-31 (health and ready); SPEC NFR-INT-001, NFR-INT-003, NFR-REC-001, NFR-MNT-002, NFR-SEC-007; NFR-MKT-DECIMAL, NFR-MKT-MIGRATIONS, NFR-MKT-OWNERSHIP; addendum B (all items), C (market service shape)
- **Priority:** Must
- **Status:** Draft code only (to be split per D9)
- **Owner:**
- **Depends on:** 2.1, 2.2, 2.3 (template merged), 2.4 (platform merged, per ingestion plan section 10 row 1)
- **Branch:** feature/market-schema

Scope: service skeleton on `libs/qs_template`, settings (`QS_*`), SQLAlchemy models, Alembic revision `0001_market_schema` creating `instrument`, `ingestion_run`, `ingestion_run_item`, `staging_bar`, `bar` (hypertable), `bar_revision`, `rejected_bar`, `data_gap`, `corporate_action`, `return_series` (hypertable), `market_environment` and its Instrument membership, `outbox`, `processed_events`, `audit_log` (with `sector` on `instrument`); `db-init` changes (database, `market` role, TimescaleDB extension). Provenance on `bar` and `bar_revision` (run id, Vendor, Ruleset version), Run item deferral reason, and planted-Instrument marking are included because later stories need them (see gaps in the final section).

**Acceptance Criteria:**

**Given** an empty database
**When** `ci/scripts/migration-check.sh market` runs
**Then** upgrade to head, downgrade to base and upgrade again all succeed

**Given** the models and the migrations
**When** the model-matches-migration test runs
**Then** it passes; it fails if a model column, type or constraint differs from the migrations

**Given** the `bar` table
**When** a row with any price at or below 0, `low > high`, open or close outside [low, high], or negative volume is inserted directly
**Then** the database refuses it

**Given** the `bar` table
**When** its columns are inspected
**Then** prices are `NUMERIC(23,8)` and volume is `NUMERIC(28,8)`, and no price column is a float type

**Given** the `market_environment` table
**When** a row whose end date is not after its start date, or whose type is not `historical_replay` or `synthetic_market`, frequency not `daily`, `hourly` or `tick`, or status not `draft`, `ready` or `active`, is inserted directly
**Then** the database refuses it

**Given** the `instrument` table
**When** a second row with the same symbol and exchange is inserted, or a status outside {active, retired}, or an inconsistent `retired_at`
**Then** the database refuses it

**Given** the migrations
**When** they run
**Then** they run as the `market` role; database, role and TimescaleDB extension creation live only in `db-init`; no `create_all` exists outside tests

**Given** the market service is running
**When** `/api/market/health` is called
**Then** it reports the build Content hash
**And** `/api/market/ready` returns 503 while the database or Redis is unreachable

**Done when:** the migration check passes locally and in Jenkins on the pull request, and the database-rule tests pass.

### Story 3.2: Admin adds, annotates, retires and lists Instruments

As an admin,
I want to add, annotate and retire Instruments through the market API, and every signed-in User to list them,
So that the system tracks exactly the Instruments I choose, with every change audited.

- **Requirements:** FR-20; FR-16, FR-18, FR-19 (market routes, Instrument audit, Instrument Events); SPEC FR-MKT-001, FR-PLT-006; MID section 6.2
- **Priority:** Must
- **Status:** Draft code only
- **Owner:**
- **Depends on:** 3.1
- **Branch:** feature/market-instruments

Add, annotate and retire are API-only (used through `/api/market/docs`); the POC Instruments page is read-only and gains no button or form (addendum section G).

**Acceptance Criteria:**

**Given** an admin
**When** they add an Instrument with symbol, name, sector, listing exchange, currency, asset class (`equity` or `etf`), optional Vendor symbol and notes
**Then** the Instrument is created as `active`
**And** `instrument.created` is published and an Audit entry is recorded

**Given** an Instrument whose symbol and exchange already exist, even if it is retired
**When** an admin adds it again
**Then** the response is HTTP 409 naming the existing Instrument id and status (re-activating a retired Instrument is out of scope)

**Given** an active Instrument
**When** an admin annotates its name, sector or notes
**Then** the change is saved and audited

**Given** an active Instrument
**When** an admin retires it
**Then** it becomes `retired`, keeps its Bars and history, still appears in history queries, and `instrument.retired` is published with an Audit entry
**And** retiring it again has no further effect

**Given** a retired Instrument
**When** any later Ingestion run is created
**Then** the Instrument is excluded from it

**Given** any signed-in User
**When** they list Instruments filtered by status
**Then** they get the matching Instruments

**Given** a quant, analyst or viewer User
**When** they add, annotate or retire an Instrument
**Then** they get HTTP 403

**Given** the market service
**When** the role-by-route matrix test calls every Instrument route with each of the four Roles
**Then** each returns the expected 2xx or 403

**Done when:** API tests pass, including the 409, 403 and idempotent-retire cases.

### Story 3.3: Seed the starting universe of 40 Instruments

As an admin,
I want one command that loads the 40-Instrument starting universe,
So that a fresh Environment is ready for ingestion without typing 40 symbols.

- **Requirements:** FR-20 (seed); AR-8 (D5)
- **Priority:** Must
- **Status:** Draft code only
- **Owner:**
- **Depends on:** 3.2
- **Branch:** feature/market-instruments

**Acceptance Criteria:**

**Given** an empty Instrument master
**When** the seed command runs
**Then** 40 Instruments exist: 30 large-cap equities and 10 ETFs, each with its name and sector so the POC Instruments page can show them

**Given** the seed has already run
**When** it runs again
**Then** nothing is added

**Given** no Symbol directory copy exists
**When** the seed command runs
**Then** it still succeeds (the seed does not depend on the directory)

**Done when:** seed loads 40 Instruments in a test and a second run adds zero.

### Story 3.4: Validate a new Instrument against the Symbol directory

As an admin,
I want the system to check the symbol against the official exchange listings and fill in the listing exchange when I add an Instrument,
So that the Instrument master holds only real, correctly placed securities.

- **Requirements:** FR-21; new, strengthens SPEC FR-MKT-001; AR-9 (addendum D)
- **Priority:** Could (cut item 1; fallback: a reviewed static seed list)
- **Status:** Not started
- **Owner:**
- **Depends on:** 3.2
- **Branch:** feature/market-symbol-directory *(new)*

Scope includes Alembic revision `0002_symbol_directory` (directory copy and its fetch time), which must pass the migration check on its own.

**Acceptance Criteria:**

**Given** a symbol listed in the Symbol directory
**When** an admin adds it
**Then** it is accepted and its exchange is set from the directory's exchange code: Nasdaq to XNAS, NYSE to XNYS, NYSE American to XASE, NYSE Arca to ARCX, Cboe BZX to BATS, IEX to IEXG

**Given** a symbol the directory marks as an ETF
**When** an admin adds it
**Then** the asset class `etf` is suggested

**Given** a symbol marked as a test issue
**When** an admin adds it
**Then** it is refused with HTTP 422, reason `test_issue`

**Given** a symbol not in the directory
**When** an admin adds it without an override reason
**Then** it is refused with HTTP 422, reason `not_listed`
**And** with an explicit override reason it is added and the reason is recorded in the Audit entry

**Given** an admin-supplied exchange that differs from the directory's
**When** the add is submitted without an override reason
**Then** it is refused with HTTP 422, reason `exchange_mismatch`; with an override reason it is accepted and audited

**Given** a directory download that fails
**When** an admin adds an Instrument
**Then** the last successful copy is used; if that copy is older than 3 days it is still used and the response carries a `stale_directory` warning

**Given** a fresh Environment with no stored copy and a failed download
**When** an admin adds an Instrument without an override reason
**Then** it is refused with HTTP 503, reason `directory_unavailable`

**Given** directory validation that takes longer than 5 seconds
**When** the timeout is reached
**Then** the system behaves as for a failed download

**Given** the directory files
**When** they are parsed
**Then** the trailer line ("File Creation Time") is skipped and the Vendor symbol is matched on a normalized share-class form

**Given** the migration `0002_symbol_directory`
**When** `migration-check.sh market` runs
**Then** up, down and up succeed

**Done when:** every response type above has an API test using stored directory fixtures (no live download in tests).

### Story 3.5: Daily Symbol directory refresh and delisted candidates

As an admin,
I want the directory refreshed daily and active Instruments that left it reported,
So that I notice delistings without the system retiring anything on its own.

- **Requirements:** FR-21 (refresh and reporting), FR-31 (directory age metric, failed refresh logged)
- **Priority:** Could (cut item 1)
- **Status:** Not started
- **Owner:**
- **Depends on:** 3.4
- **Branch:** feature/market-symbol-directory *(new)*

**Acceptance Criteria:**

**Given** a refresh command (scheduled daily by story 4.5)
**When** it runs successfully
**Then** the stored copy is replaced and active Instruments missing from the directory are marked `delisted_candidate`
**And** they are never retired automatically

**Given** a refresh that fails
**When** it ends
**Then** the failure is logged, the last copy is kept, and the directory's age is exposed as a metric

**Done when:** refresh tests pass with fixture files for success, failure and a missing Instrument.

## Epic 4: Ingestion runs that survive the Vendor

Admins get Ingestion runs on a schedule and on demand. The Vendor adapter bounds and retries every call within a shared Vendor budget; the run worker executes one run at a time, records Run items, and defers instead of hanging when the Vendor fails. Records fetched here are staged; Epic 5 adds the Cleaning gate and publication.

### Story 4.1: Tiingo Vendor adapter with timeouts, retries and recorded fixtures

As an admin,
I want every Vendor call bounded by a timeout and retried only for transient failures,
So that a slow or failing Vendor degrades a run instead of hanging it.

- **Requirements:** FR-24; SPEC NFR-PERF-005, NFR-REL-006; MID section 7.6 ("External data source unavailable", "Malformed provider response"); AR-6
- **Priority:** Must
- **Status:** Draft code only
- **Owner:**
- **Depends on:** 3.1
- **Branch:** feature/market-tiingo-adapter

**Acceptance Criteria:**

**Given** any Vendor call
**When** the Vendor does not answer
**Then** the call times out after at most 30 seconds

**Given** a timeout, HTTP 5xx or HTTP 429
**When** the adapter receives it
**Then** it retries with backoff up to 4 attempts in total, honouring a `Retry-After` header

**Given** an unknown symbol or a refused request
**When** the adapter receives it
**Then** it does not retry

**Given** a malformed Vendor response
**When** the adapter parses it
**Then** it raises `malformed_response` and nothing from that response is returned for publication

**Given** a Vendor authentication failure (HTTP 401 or 403)
**When** the adapter receives it
**Then** it raises `vendor_auth`

**Given** an Environment configured with the fixture Vendor
**When** a run fetches
**Then** recorded responses are served instead of calling Tiingo

**Given** the automated test suite
**When** it runs
**Then** no test calls the real Vendor; recorded responses cover success, empty, 404, 429 with `Retry-After` then success, 500 then success, malformed JSON, and the auth header is sent

**Done when:** adapter tests pass for every response type.

### Story 4.2: Shared hourly Vendor budget

As an admin,
I want one Vendor budget shared by every worker and Environment using the same key, with a reserve for the daily runs,
So that we never exceed the Vendor's free limits and backfills never starve the daily run.

- **Requirements:** FR-24 (budget), FR-22 (reservation); SPEC NFR-PERF-005; SM-C4
- **Priority:** Must
- **Status:** Draft code only
- **Owner:**
- **Depends on:** 4.1
- **Branch:** feature/market-tiingo-adapter

**Acceptance Criteria:**

**Given** several workers and Environments using the same Vendor API key
**When** they call the Vendor concurrently
**Then** combined usage never exceeds the configured hourly budget (default 45)

**Given** the budget is exhausted
**When** a caller asks for a request
**Then** it is told to defer rather than wait for the next hour

**Given** a backfill or manual run
**When** it requests budget
**Then** it cannot spend the part reserved for that day's `daily` and `catchup` runs: one request per active Instrument per run

**Done when:** rate-limiter tests pass with concurrent callers against a test Redis.

### Story 4.3: Run worker executes Ingestion runs one at a time with deferral

As an admin,
I want each Ingestion run executed by exactly one worker, recorded per Instrument, and degraded rather than stuck when the Vendor fails,
So that I can see exactly what each run did and why.

- **Requirements:** FR-22 (run records), FR-23 (one worker at a time, interrupted run), FR-24 (circuit, deferral, auth failure, unknown symbol, malformed); SPEC FR-MKT-002, NFR-REL-005, NFR-REL-006; AR-3
- **Priority:** Must
- **Status:** Draft code only
- **Owner:**
- **Depends on:** 3.2, 4.1, 4.2
- **Branch:** feature/market-pipeline (run queue, worker with lock and recovery, staging, circuit breaker; publication is split into story 5.3)

**Acceptance Criteria:**

**Given** two workers running
**When** a run is pending
**Then** only one worker executes it at a time

**Given** a worker that crashes mid-run
**When** the next worker claims work
**Then** the run is reset to pending and re-run safely

**Given** a run
**When** it executes
**Then** it records mode, status, window, requesting User (or `scheduler`), Ruleset version, start and finish times, and error, plus one Run item per Instrument with counts and error
**And** raw Vendor records are stored untouched in `staging_bar`

**Given** 5 consecutive Vendor failures (timeouts, HTTP 5xx or HTTP 429 only; unknown symbols do not count)
**When** the fifth occurs
**Then** the remaining Instruments are deferred and the run ends `partially_succeeded`, naming the deferred Instruments

**Given** a Vendor authentication failure (HTTP 401 or 403)
**When** it occurs
**Then** the whole run ends at once as `failed` with reason `vendor_auth`, and no further Vendor calls are made

**Given** the Vendor budget is exhausted
**When** Instruments remain
**Then** they are deferred rather than the run waiting

**Given** an unknown symbol
**When** it is fetched
**Then** only its own Run item fails, with a reason, and the other Instruments continue

**Given** a malformed Vendor response
**When** it is received
**Then** its Run item fails with reason `malformed_response` and nothing from that response is published

**Given** an Instrument deferred by 2 consecutive runs
**When** the runs end
**Then** its deferral count is recorded for the data-quality view (story 6.4)

**Given** a run whose window contains no new Sessions (for example on a weekend)
**When** it executes
**Then** it ends `succeeded` with zero new Bars

**Done when:** database pipeline tests pass for the lock, crash recovery, circuit breaker, auth failure, budget deferral and unknown-symbol cases.

### Story 4.4: Admin triggers manual and backfill runs

As an admin,
I want to trigger a manual run (optional window and Instrument list) or a backfill and get an acknowledgement at once,
So that I can fetch data on demand without waiting for the work to finish.

- **Requirements:** FR-22; SPEC FR-MKT-002, NFR-PERF-004; MID FR-01; FR-16
- **Priority:** Must (manual runs; backfill limited to 2 years if cut item 3 applies)
- **Status:** Not started
- **Owner:**
- **Depends on:** 4.3
- **Branch:** feature/market-api-and-scheduler

Triggering is API-only (through `/api/market/docs` or the command line); no POC page has a trigger control (addendum section G).

**Acceptance Criteria:**

**Given** an admin
**When** they trigger a `manual` or `backfill` run
**Then** the response is HTTP 202 with the run id within 800 ms, and the work proceeds asynchronously

**Given** no explicit window
**When** a run is created
**Then** each Instrument's window starts 5 Sessions before its last stored Bar and ends at the latest Session whose close has passed, using the exchange's local date (America/New_York for XNYS)
**And** a new Instrument starts at the backfill start date

**Given** a `backfill` trigger with no start date
**When** it is created
**Then** it starts at 2015-01-02

**Given** an unfinished run whose Instruments and window overlap the requested ones
**When** an admin triggers a run
**Then** the response is HTTP 409 with the id of the active run

**Given** a quant, analyst or viewer User
**When** they trigger a run
**Then** they get HTTP 403

**Done when:** API tests pass for 202 timing, 409 overlap and 403, and a command-line trigger exists for operators.

### Story 4.5: Scheduler creates daily and catch-up runs

As an admin,
I want a `daily` run at 22:30 UTC and a `catchup` run at 06:00 UTC every day, created exactly once,
So that fresh data arrives every trading day without babysitting.

- **Requirements:** FR-22; SPEC FR-MKT-002; SM-4
- **Priority:** Must (`daily`); the `catchup` run is Could (cut item 3)
- **Status:** Not started
- **Owner:**
- **Depends on:** 4.4
- **Branch:** feature/market-api-and-scheduler

**Acceptance Criteria:**

**Given** the scheduler
**When** 22:30 UTC and 06:00 UTC arrive on any calendar day
**Then** one `daily` and one `catchup` run are created for every active Instrument

**Given** the schedule fires twice (for example two scheduler instances)
**When** both try to create the run
**Then** only one `daily` run exists for the date

**Given** a backfill in progress
**When** 22:30 UTC arrives
**Then** the `daily` run starts within 15 minutes

**Given** the Environment configuration
**When** the services start
**Then** the scheduler is enabled in exactly one Environment per Vendor API key (TEST in Iteration 1); other Environments create runs only when an admin triggers them

**Given** story 3.5 is delivered
**When** the scheduler runs daily
**Then** it also invokes the Symbol directory refresh

**Done when:** scheduler tests show one run per date under duplicate firing and the daily-start bound under a running backfill.

## Epic 5: Cleaning gate, Revisions and reconciliation

Every staged record passes the Cleaning gate. Clean records become Bars with UTC session-close timestamps; rejected records are kept with every rule they broke; Data gaps are recorded only when a session is truly late; re-runs add nothing; changed vendor values become Revisions; every run's Reconciliation report adds up.

### Story 5.1: Cleaning rules and trading-calendar timestamps

As an analyst,
I want every vendor record checked against named Cleaning rules with explicit severities,
So that I know exactly why a record was rejected, corrected or flagged.

- **Requirements:** FR-25; SPEC FR-MKT-011, NFR-INT-001; MID FR-02, TC-02, TC-03; AR-4, AR-5, AR-7
- **Priority:** Must
- **Status:** Draft code only
- **Owner:**
- **Depends on:** 3.1
- **Branch:** feature/market-cleaning-gate

**Acceptance Criteria:**

**Given** a record with a missing or unparsable field
**When** the gate runs
**Then** it is rejected under `malformed`

**Given** a record for a date the run did not request
**When** the gate runs
**Then** it is rejected under `outside_window`

**Given** a record dated on a weekend or exchange holiday
**When** the gate runs
**Then** it is rejected under `non_trading_day`

**Given** a record with any price at or below 0
**When** the gate runs
**Then** it is rejected under `non_positive_price`

**Given** a record with low above high, or open or close outside [low, high]
**When** the gate runs
**Then** it is rejected under `ohlc_order`

**Given** a record with volume below 0
**When** the gate runs
**Then** it is rejected under `negative_volume`

**Given** the same Session twice with different values
**When** the gate runs
**Then** all copies are rejected under `duplicate_conflict`

**Given** the same Session twice with identical values
**When** the gate runs
**Then** one copy is kept and the other is counted under `duplicate_removed` (correct)

**Given** a record with volume equal to 0
**When** the gate runs
**Then** it is published with the `zero_volume` Quality flag

**Given** a record whose absolute log return from the previous close exceeds 0.405
**When** it is not a split day
**Then** it is published with the `outlier` flag, or rejected when the outlier policy is configured to reject
**And** on a split day the outlier rule is skipped

**Given** a record that breaks several rules
**When** it is rejected
**Then** every rule it broke and its raw payload are kept; it is never silently dropped

**Given** generated inputs (property test)
**When** the gate runs
**Then** it never publishes a Bar with a price at or below 0 or high below low

**Given** a published Bar
**When** its timestamp is read
**Then** it is the Session's actual close in UTC from the Trading calendar, correct across a daylight-saving change and on an early-close day

**Given** a gate run
**When** it completes
**Then** the Ruleset version `2026.10.1` is reported for storage on the run

**Done when:** one unit test per rule (pass and fail), the property test, and the calendar tests pass; prices stay `Decimal` throughout.

### Story 5.2: Reconciliation report that always adds up

As an analyst,
I want a per-run and per-Instrument report of received, passed untouched, corrected, duplicates removed and rejected records,
So that I can trust that nothing was lost or double counted.

- **Requirements:** FR-26; SPEC FR-MKT-011, FR-MKT-002; MID FR-02
- **Priority:** Must
- **Status:** Draft code only
- **Owner:**
- **Depends on:** 5.1
- **Branch:** feature/market-cleaning-gate

**Acceptance Criteria:**

**Given** any input to the gate (property test)
**When** the report is built for each Instrument and for the run total
**Then** received = passed untouched + corrected + duplicates removed + rejected

**Given** a completed run
**When** its report is read
**Then** it lists counts per Cleaning rule, Quality flags, new and resolved Data gaps, new Bars and Revisions

**Done when:** the property test passes and the report format is fixed for story 8.2's expected report.

### Story 5.3: Publish clean Bars idempotently, with Revisions, Rejected bars and Data gaps

As a quant,
I want re-runs to add nothing and vendor corrections to appear as numbered Revisions with the old values kept,
So that the same query returns the same answer tomorrow unless a recorded Revision explains the difference.

- **Requirements:** FR-23, FR-25 (Rejected bars, Data gaps, Ruleset version stored), FR-26 (report stored on the run), FR-19 (`bar.ingested`, `bar.corrected`); SPEC FR-MKT-002, FR-MKT-011, NFR-REL-005, NFR-REL-008; MID TC-01; AR-7 (D2)
- **Priority:** Must
- **Status:** Draft code only
- **Owner:**
- **Depends on:** 4.3, 5.2
- **Branch:** feature/market-publishing *(new; split from ingestion plan row 5)*

**Acceptance Criteria:**

**Given** an identical window run twice
**When** the second run ends
**Then** it produced zero new Bars, zero Revisions and zero Events

**Given** one vendor close value changed for an already-published Bar
**When** the window is re-run
**Then** exactly one Revision and one `bar.corrected` Event are produced, the Bar's revision number increases, and the previous value can be read

**Given** a vendor correction that fails the Cleaning gate
**When** it is processed
**Then** no Revision is created, the published Bar stays as it was, and the corrected record is stored as a Rejected bar

**Given** a run interrupted mid-way
**When** it is re-run
**Then** the final Bars, Revisions and Events equal those of an uninterrupted run

**Given** an expected Session with no clean Bar
**When** its close plus 12 hours has passed (so the 06:00 UTC catch-up run is the first to judge it)
**Then** it is recorded as a Data gap
**And** holidays are never recorded as gaps, and the gap resolves when its Bar arrives

**Given** a completed run
**When** it is stored
**Then** the Ruleset version and the Reconciliation report are stored on the run, and `bar.ingested` is published through the outbox for each affected Instrument

**Done when:** database pipeline tests pass for first insert, identical re-run, correction, rejected correction, interruption and gap resolution.

## Epic 6: Returns, corporate actions and the market read API

The engine computes one Return series, records Corporate actions and keeps raw and adjusted prices. Signed-in Users read Instruments, Bars and returns; admins, quants and analysts read run history, Rejected bars and data quality. Operators get structured logs and metrics.

### Story 6.1: Compute and publish returns and volatility

As a quant,
I want log returns, adjusted log returns and 20- and 60-session volatility computed once after every run,
So that no downstream module re-derives them differently.

- **Requirements:** FR-27; SPEC FR-MKT-003
- **Priority:** Must
- **Status:** Draft code only
- **Owner:**
- **Depends on:** 5.3
- **Branch:** feature/market-returns *(new; the ingestion plan puts the formulas in row 3 and the recomputation in row 5)*

**Acceptance Criteria:**

**Given** consecutive Sessions
**When** returns are computed
**Then** log return = ln(close_t / close_t-1), the adjusted log return uses the Vendor's split- and dividend-adjusted close, and N-session volatility is the sample standard deviation (n - 1) of the last N adjusted log returns times the square root of 252, undefined until N returns exist

**Given** the hand-computed fixture
**When** the values are compared
**Then** they match to within 1 x 10^-8 absolute

**Given** a split day
**When** the adjusted log return is read
**Then** it shows no jump, and a dividend day's adjusted log return equals the hand-computed value from the adjusted closes

**Given** a Revision on an old Session
**When** returns are recomputed
**Then** recomputation starts at that Session and changes nothing earlier

**Given** a run that added or revised Bars
**When** it ends
**Then** the Return series is stored for each affected Instrument from the earliest new or revised Session and published in the `bar.ingested` Event

**Done when:** returns unit tests and the recompute-from-revision database test pass.

### Story 6.2: Record corporate actions and serve adjusted prices

As a quant,
I want splits and cash dividends recorded and both raw and adjusted price series kept,
So that I can backtest on adjusted history without ever losing the raw values.

- **Requirements:** FR-28; SPEC FR-MKT-010 (Extended); AR-7 (D3)
- **Priority:** Could (cut item 2; fallback keeps the Vendor-adjusted close for FR-27)
- **Status:** Draft code only
- **Owner:**
- **Depends on:** 5.3
- **Branch:** feature/market-corporate-actions *(new)*

**Acceptance Criteria:**

**Given** a split in the Vendor data
**When** it is ingested
**Then** exactly one Corporate action with a split factor greater than 0 is created
**And** Bars requested with `adjusted=true` are adjusted for it

**Given** a cash dividend in the Vendor data
**When** it is ingested
**Then** exactly one Corporate action with the cash amount is created on its ex-date Session

**Given** adjusted values
**When** they are computed or served
**Then** raw Bars are never overwritten

**Done when:** pipeline tests pass with a recorded split and a recorded dividend.

### Story 6.3: Read Instruments, Bars and returns through the market API

As a quant,
I want to read raw or adjusted Bars and the Return series for an Instrument and date range, paginated,
So that I can pull ten years of history for a backtest with exact values and provenance.

- **Requirements:** FR-29; FR-16; SPEC FR-MKT-001, FR-MKT-002, FR-MKT-003, NFR-PERF-002, NFR-MNT-005 (partial); MID FR-03, TC-04
- **Priority:** Must
- **Status:** Draft schemas only
- **Owner:**
- **Depends on:** 6.1
- **Branch:** feature/market-read-api *(new; split from ingestion plan row 6)*

This API feeds the POC Instruments page (Symbol, Name, Sector, Price, Chg %) and the POC Market Data page (daily candles for the last 90 sessions); wiring those pages replaces their mock data only (addendum section G).

**Acceptance Criteria:**

**Given** any signed-in User
**When** they list Instruments
**Then** each Instrument returns `symbol`, `name`, `sector`, `price` (the latest clean close) and `change_pct` (the change from the previous clean close)
**And** an Instrument with fewer than two clean Bars returns no price or change, and the POC page shows it without them

**Given** any signed-in User
**When** they request Bars for an Instrument and window
**Then** Bars are returned in Session order with exact decimal prices, revision numbers and Quality flags, paginated, which is what the POC Market Data page draws for the last 90 sessions

**Given** a Bar
**When** it is returned
**Then** it carries its provenance: the Ingestion run that published its current revision, the Vendor and the Ruleset version; previous revisions carry the same fields

**Given** `adjusted=true` and story 6.2 is delivered
**When** Bars are requested
**Then** adjusted prices are returned; without story 6.2 the Vendor-adjusted close is still available through the Return series

**Given** any signed-in User
**When** they request the Return series for an Instrument and window
**Then** log return, adjusted log return and both volatilities are returned in Session order

**Given** every build
**When** the pipeline runs
**Then** the OpenAPI document is exported and the frontend's typed client is generated from it

**Given** a viewer
**When** they read Instruments, Bars or returns
**Then** the read succeeds (2xx)

**Done when:** API tests pass, the role matrix covers these routes, and the OpenAPI export is in CI. Latency is measured in story 8.4.

### Story 6.4: Run history, Rejected bars and data-quality summary

As an analyst,
I want run history, run detail with its report, Rejected bars with reasons and a data-quality summary through the market API, and each finished run on the Audit Log page,
So that I can judge data quality before relying on it.

- **Requirements:** FR-29; FR-18 (audit feed); FR-21 (`delisted_candidate`, `stale_directory` shown), FR-24 (deferral count shown), FR-16; SPEC FR-MKT-011, FR-MKT-002
- **Priority:** Must
- **Status:** Draft schemas only
- **Owner:**
- **Depends on:** 5.3 (and 3.5, 4.3 for the extra data-quality fields); the platform's readable activity feed for the Audit Log page (PRD Open Question 14)
- **Branch:** feature/market-read-api *(new)*

Run history, run detail, Rejected bars and the data-quality summary are API-only (used through `/api/market/docs`); no POC screen shows them and none is added (addendum section G).

**Acceptance Criteria:**

**Given** an admin, quant or analyst
**When** they read the run history and a run's detail
**Then** they see each run's mode, status, window, requester, Ruleset version, times, error, Run items and Reconciliation report

**Given** an admin, quant or analyst
**When** they read a run's Rejected bars
**Then** each record shows every rule it broke and its raw payload

**Given** an admin, quant or analyst
**When** they read the data-quality summary
**Then** each Instrument shows its last clean Session, Bar count, open Data gaps and flagged Bars, and can be sorted by open gaps
**And** Instruments deferred by 2 consecutive runs show their deferral count; `delisted_candidate` Instruments and a `stale_directory` warning are shown when story 3.5 is delivered
**And** planted fixture Instruments are excluded from the totals of real Instruments

**Given** a viewer
**When** they read run history, Rejected bars or data quality
**Then** they get HTTP 403

**Given** an Ingestion run that finishes
**When** its final status is recorded
**Then** exactly one event is added to the platform audit feed that the POC Audit Log page reads: user (the requesting User, or `System` for scheduled runs), service `Market Data`, action `Ingestion run completed`, `Ingestion run partially succeeded` or `Ingestion run failed`, severity `Info` (nothing rejected), `Warning` (rejections, gaps or deferrals) or `Critical` (failed), and a one-line detail with the counts and the rejecting rules

**Done when:** API tests pass including the viewer 403 cases, and a test asserts one audit feed event per finished run with the fields above.

### Story 6.5: Market data observability

As an admin,
I want structured logs and metrics for every run, Vendor call and outbox drain,
So that I can see failures and staleness without reading code.

- **Requirements:** FR-31; SPEC NFR-OBS-002, NFR-OBS-003
- **Priority:** Should (logs plus health and ready at minimum); the full metrics list is Could (cut item 4)
- **Status:** Template logging done; market not started
- **Owner:**
- **Depends on:** 4.3, 5.3
- **Branch:** feature/market-observability *(new)*

**Acceptance Criteria:**

**Given** any log line from ingestion
**When** it is emitted
**Then** it carries the run id, the Instrument and the Vendor, and never contains the Vendor API key

**Given** the metrics endpoint
**When** it is scraped
**Then** metrics exist for runs by status and run duration, Bars by outcome and rejections by rule, Vendor calls by status and latency, Vendor budget waits and circuit state, and outbox backlog

**Done when:** a test asserts the log fields and the absence of the key, and each metric name is present after a test run.

## Epic 7: Market environments

Admins and quants create Market environments that the API and the database both validate, with exactly the fields of the POC Market Environments and Create Market Environment pages, and the tick Event schema of the Market environment interface is published for Iteration 2. Replay playback (the POC Replay page stays on mock data) and synthetic generation are out of scope.

### Story 7.1: Create, list and read Market environments

As a quant,
I want to create a named Market environment over existing Instruments, a date window and a frequency, and see it on the POC Market Environments page,
So that Iteration 2 can replay or simulate it without redefining it.

- **Requirements:** FR-30; FR-16; SPEC FR-MKT-007 (create), FR-MKT-008, NFR-INT-003
- **Priority:** Must
- **Status:** Draft schemas only
- **Owner:**
- **Depends on:** 3.2
- **Branch:** feature/market-environments *(new; split from ingestion plan row 6)*

The API serves the POC Create Market Environment page (type, universe Instruments, data window, frequency) and the POC Market Environments page (Environment, Type, Universe, Window, Frequency, Status); wiring them replaces their mock data only. The API uses lower-case values (`historical_replay`, `daily`, `draft`) that the frontend client maps to the POC labels (addendum section G).

**Acceptance Criteria:**

**Given** an admin or quant
**When** they create a Market environment with a name, a type (`historical_replay` or `synthetic_market`), a universe name, 1 to 100 existing Instruments, a start date, an end date after it, and a frequency (`daily`, `hourly` or `tick`)
**Then** it is created with status `draft`

**Given** any signed-in User
**When** they list or read Market environments
**Then** each returns its name, type, universe, Instruments, start and end date, frequency and status

**Given** an end date that is not after the start date
**When** the Market environment is created through the API
**Then** it is refused with HTTP 422
**And** a direct database insert of the same row is also refused

**Given** zero Instruments, more than 100, an unknown Instrument, or a type, frequency or status outside the POC's values
**When** the Market environment is created
**Then** it is refused with HTTP 422, and the database refuses the same type, frequency or status when inserted directly

**Given** an analyst or viewer
**When** they create a Market environment
**Then** they get HTTP 403

**Done when:** API tests pass, including the inverted-window case used in the demo spine.

### Story 7.2: Publish the Market environment tick Event schema

As a developer,
I want the tick Event schema of the Market environment interface versioned in the repository,
So that replayed and simulated markets share one contract a portfolio can bind to.

- **Requirements:** FR-30; SPEC FR-MKT-009 (partial: schema only), NFR-INT-003
- **Priority:** Must
- **Status:** Draft schemas only
- **Owner:**
- **Depends on:** 3.1
- **Branch:** feature/market-environments *(new)*

**Acceptance Criteria:**

**Given** the repository
**When** `contracts/events/` is inspected
**Then** the tick Event schema exists with a schema version

**Given** sample tick Events, valid and invalid
**When** the automated test validates them
**Then** valid samples pass and invalid samples fail

**Done when:** the schema and its test are merged; the binding operations are recorded as Iteration 2 work.

## Epic 8: Mid demo evidence

The market service reaches DEV and TEST through the pipeline; the Planted-fault dataset proves the Cleaning gate exactly; the demo spine is rehearsed; and the measured NFR and traceability evidence is ready for the Mid report.

### Story 8.1: Market service deploys to DEV and TEST through the pipeline

As a developer,
I want the market service added as a Component with its migrate step and secrets,
So that it ships through the same gates as every other Component.

- **Requirements:** FR-13 (market), FR-9 (market secrets), FR-22 (scheduler only on TEST), FR-31 (health smoke), FR-17 (market-side revocation); SPEC NFR-MNT-004, NFR-REC-001, NFR-SEC-003, NFR-SEC-007
- **Priority:** Must (backend on ACC and PROD is Could item 6)
- **Status:** Not started
- **Owner:**
- **Depends on:** 2.7, 4.5, 6.3, 6.4, 7.1
- **Branch:** feature/market-deployment

Scope: Dockerfile, compose entries `market`, `market-worker`, `market-scheduler`, `market-relay`, `market-migrate`; `db-init` market database and role; `ci/components.conf` entry; `TIINGO_API_KEY` and `MARKET_DB_PASSWORD` in the encrypted files; README and runbook (re-run a window, backfill an Instrument, retire a delisted symbol, read a run report through the API docs).

**Acceptance Criteria:**

**Given** the `market` Component entry
**When** it is merged
**Then** `market` passes the pull request checks, deploys to DEV and TEST, and passes a Smoke test on `/api/market/health` reporting the deployed Content hash

**Given** a deploy whose `market-migrate` step fails
**When** the deploy runs
**Then** the previous version keeps running and the build is marked failed

**Given** DEV and TEST
**When** they run
**Then** the scheduler is enabled only on TEST

**Given** a User deactivated in the Platform on TEST
**When** their earlier token is presented to the market service
**Then** it is refused within 5 seconds

**Given** the repository, Images and build logs
**When** they are searched
**Then** the Tiingo key appears in none of them

**Done when:** `market` is green in DEV and TEST with `quantsim/test-verified`.

### Story 8.2: Planted-fault dataset with an exact expected report

As an analyst,
I want a fixed dataset of known defects and the exact report the Cleaning gate must produce for it,
So that the panel sees every planted defect caught by the rule that should catch it.

- **Requirements:** FR-26 (exact match), FR-25, FR-24 (fixture Vendor, planted Instruments); SM-2; MID TC-02, TC-03, and the new TCs for the re-run and planted-fault exact match (addendum F)
- **Priority:** Must
- **Status:** Not started
- **Owner:**
- **Depends on:** 8.1
- **Branch:** feature/market-planted-faults

**Acceptance Criteria:**

**Given** the Planted-fault dataset (bad OHLC order, negative price, weekend date, identical and conflicting duplicates, a 60% jump, zero volume, a missing Session)
**When** it is ingested through the fixture Vendor
**Then** the Reconciliation report equals the stored expected report field for field, in CI and on DEV and TEST

**Given** the same planted window
**When** it is run a second time
**Then** the report shows zero new Bars and zero new Events

**Given** the fixture Vendor on TEST
**When** it serves planted data
**Then** the data is ingested only for dedicated planted Instruments, marked as such, and excluded from SM-4 and from real Instruments' data-quality totals

**Given** DEV with a real Vendor key
**When** an admin triggers a run on 3 real symbols
**Then** Bars, the report and Events land in DEV

**Done when:** SM-2 holds (100% match on DEV and TEST).

### Story 8.3: Demo spine script and rehearsal on TEST

As an admin,
I want a written, rehearsed demo script that runs from a fresh TEST deploy,
So that the Mid-I demo passes the same way every time.

- **Requirements:** SM-1 (validates FR-14 to FR-16, FR-20 to FR-26, FR-29, FR-30); UJ-1
- **Priority:** Must
- **Status:** Not started
- **Owner:**
- **Depends on:** 8.2
- **Branch:** feature/market-planted-faults

**Acceptance Criteria:**

**Given** a fresh TEST deploy
**When** the script is followed
**Then** an admin signs in on the POC sign-in page, adds three Instruments through the market service's API docs (confirmed against the Symbol directory when story 3.4 is delivered), and sees them listed on the POC Instruments page
**And** the admin triggers a run through the API docs and gets HTTP 202 at once
**And** when the run finishes, the POC Audit Log page shows a Market Data event "Ingestion run completed" with severity Warning and a detail line counting received, passed untouched, corrected and rejected and naming the rules that rejected the planted defects
**And** the full Reconciliation report, read through the API docs, adds up exactly, and the POC Market Data page draws the clean Bars

**Given** the same window
**When** it is triggered again
**Then** the new Audit Log event reports zero new Bars, and no new Events are published

**Given** a viewer account
**When** it tries to add an Instrument
**Then** it is refused with HTTP 403

**Given** a Market environment whose end date is not after its start date
**When** it is created
**Then** it is refused with HTTP 422

**Given** the Vendor is unreachable during the demo
**When** the planted-fault part runs
**Then** it is unaffected because it uses recorded responses

**Done when:** the spine passes twice in a row at the rehearsal (I1-52).

### Story 8.4: Measured NFR and traceability evidence for the Mid report

As a developer,
I want the performance targets measured on TEST and every FR traced to a test or demo step,
So that each claim in the Mid report rests on observable evidence.

- **Requirements:** NFR-PERF-002, NFR-PERF-003; SM-4, SM-5, SM-7; FR-29 (p95 consequence)
- **Priority:** Must (NFR-PERF-002 measurement is an FR-29 consequence); SM-4 log depends on an always-on CI host
- **Status:** Not started
- **Owner:**
- **Depends on:** 8.1
- **Branch:** feature/mid-evidence *(new)*

**Acceptance Criteria:**

**Given** TEST behind the gateway
**When** 200 sequential requests from one client read a 1-year window of one Instrument
**Then** p95 latency is at most 800 ms, and the result is recorded in the Mid report
**And** platform user operations are measured the same way

**Given** `instrument` inserts with and without audit triggers
**When** write latency is measured once
**Then** the overhead is recorded (target at most 20%)

**Given** the last 5 trading days before Mid-I with an always-on CI host
**When** the scheduled `daily` runs on TEST are reviewed
**Then** at least 4 days ended `succeeded` for all 40 real Instruments and no day is missing a run; without an always-on host, a log of manual runs replaces this

**Given** every FR in the PRD
**When** the traceability table is built
**Then** each FR has at least one automated test or recorded demo step that references it (SM-7), and the median pull request check time is recorded (SM-5)

**Done when:** the numbers and the traceability table are in the Mid report draft.

## Story-level Requirements Coverage Map

| PRD FR | Stories | Tier |
|---|---|---|
| FR-1 | 1.1 (frontend, done), 2.7 (backend) | Must |
| FR-2 | 1.2 | Must |
| FR-3 | 1.3 | Must |
| FR-4 | 1.7 | Should |
| FR-5 | 1.8 | Should |
| FR-6 | 1.6 | Should |
| FR-7 | 1.9 | Should |
| FR-8 | 1.4 | Must |
| FR-9 | 1.5, 8.1 | Must |
| FR-10 | 1.10 | Could (untiered) |
| FR-11 | 1.11 | Should |
| FR-12 | 1.12 | Could |
| FR-13 | 2.7 (platform), 8.1 (market) | Must |
| FR-14 | 2.4 | Must |
| FR-15 | 2.1 (verification), 2.5 (sign-in) | Must |
| FR-16 | 2.1, 3.2, 4.4, 6.3, 6.4, 7.1 | Must |
| FR-17 | 2.6, 8.1 | Should |
| FR-18 | 2.2, 3.2, 3.4 (override reason) | Must |
| FR-19 | 2.3, 3.2, 5.3, 6.1 | Must |
| FR-20 | 3.1, 3.2, 3.3 | Must |
| FR-21 | 3.4, 3.5, 6.4 | Could |
| FR-22 | 4.2, 4.3, 4.4, 4.5, 8.1 | Must (catch-up and full backfill Could) |
| FR-23 | 4.3, 5.3 | Must |
| FR-24 | 4.1, 4.2, 4.3, 6.4, 8.2 | Must |
| FR-25 | 3.1, 5.1, 5.3, 8.2 | Must |
| FR-26 | 5.2, 5.3, 8.2 | Must |
| FR-27 | 6.1 | Must |
| FR-28 | 6.2 | Could |
| FR-29 | 6.3, 6.4 (incl. Audit Log event per run), 8.4 | Must |
| FR-30 | 3.1, 7.1, 7.2 | Must |
| FR-31 | 3.1 (health, ready), 3.5 (directory age), 6.5, 8.1 | Should (full metrics Could) |

| NFR | Stories |
|---|---|
| NFR-PERF-002 | 6.3, 8.4 |
| NFR-PERF-003 | 8.4 |
| NFR-PERF-004 | 4.4 |
| NFR-PERF-005 | 2.1, 4.1, 4.2 |
| NFR-REL-005/007/008 | 2.3, 4.3, 5.3 |
| NFR-REL-006 | 2.1, 2.3, 4.1, 4.3 |
| NFR-INT-001 | 3.1, 5.1, 6.3 |
| NFR-INT-002 | 2.4 |
| NFR-INT-003 | 3.1, 7.1, 7.2 |
| NFR-INT-005 | 2.2 |
| NFR-SEC-001 | 2.1, 2.5 |
| NFR-SEC-003 | 1.5, 8.1 |
| NFR-SEC-004 | 2.4 |
| NFR-SEC-007 | 3.1, 8.1 |
| NFR-AUD-001/002 | 2.2, 3.2 |
| NFR-OBS-002/003 | 2.3, 6.5 |
| NFR-REC-001 | 2.7, 3.1, 3.4, 8.1 |
| NFR-MNT-001/002/004/006 | 1.2, 1.3, 1.4, 2.7, 8.1 |
| NFR-MNT-005 (partial) | 6.3 |
| NFR-PIPE-FREE, -REPRO, -LEASTPRIV | 1.10 |
| NFR-MKT-DECIMAL, -MIGRATIONS, -OWNERSHIP | 3.1 |

### Story count per epic

| Epic | Stories |
|---|---|
| 1 Safe delivery pipeline | 12 (1.1 to 1.12) |
| 2 Platform foundation | 7 (2.1 to 2.7) |
| 3 Instrument master | 5 (3.1 to 3.5) |
| 4 Ingestion runs and Vendor access | 5 (4.1 to 4.5) |
| 5 Cleaning gate and reconciliation | 3 (5.1 to 5.3) |
| 6 Returns, corporate actions, read API | 5 (6.1 to 6.5) |
| 7 Market environments | 2 (7.1 to 7.2) |
| 8 Mid demo evidence | 4 (8.1 to 8.4) |
| **Total** | **43** |

### Validation notes (step 4)

- Every FR-1 to FR-31 maps to at least one story; every cross-cutting NFR in PRD section 5 maps to at least one story; deferred Core NFRs are listed and intentionally have no story.
- No story depends on a later story in its epic, and no epic depends on a later epic. FR-13 is placed in stories 2.7 and 8.1 rather than Epic 1 for that reason.
- Deliberate exception to "create tables only when needed": story 3.1 creates the whole Iteration 1 market schema in `0001_market_schema`, because the ingestion plan and addendum section B make the schema its own reviewed branch. The Could-tier Symbol directory adds its own revision `0002_symbol_directory` (story 3.4).
- Branches split from the ingestion plan's section 10 rows (marked *(new)*): `feature/market-publishing`, `feature/market-returns`, `feature/market-corporate-actions`, `feature/market-read-api`, `feature/market-environments`, `feature/market-observability`, plus `feature/market-symbol-directory`, `feature/release-tagging`, `feature/environment-secrets` and `feature/mid-evidence`. `feature/market-pipeline` and `feature/market-api-and-scheduler` keep their names with narrower scope.
- UI contract check (2026-10-11): no story adds a POC screen, field, column or control; Instrument changes, run triggers, run history, Rejected bars and data quality are API-only; Replay session was replaced by Market environment as the POC models it (PRD glossary, FR-30).
- Status stays `draft` until the team reviews this document.
