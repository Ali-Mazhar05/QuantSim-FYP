# QuantSim Iteration Plan

Delivery plan for the whole application, with Iteration 1 (the FYP-1 Mid gate) broken
into owner-assigned tasks. It follows the four iterations committed in the proposal
defence and the build order in the tech stack guide (§14), and maps every task to the
requirement it satisfies.

**Status key:** ✅ done · 🔄 in progress · ⬜ not started · ⏸ deferred (Extended)

**Owners** follow the proposal's member split. Replace A, B and C with names.

| Member | Area | Iteration 1 focus |
|---|---|---|
| A | Platform / infrastructure | Shared service template, infrastructure stack, M0 identity, CI/CD |
| B | Market data / simulation / risk | M1 ingestion, cleaning gate, returns and volatility |
| C | ML / frontend | Data schemas, API client, live frontend pages |

---

## 1. The four iterations

| Iteration | Months | Gate | Theme | Modules and requirements |
|---|---|---|---|---|
| **1** | Sep–Oct 2026 | **Mid-I** | Foundations | CI/CD; shared service template; infrastructure stack; **M0** identity, roles, audit (FR-PLT-001..008); **M1** instruments, ingestion, cleaning, returns and volatility (FR-MKT-001, 002, 003, 011), correlation series (FR-MKT-004); market-environment interface (FR-MKT-009) and replay-session validation (FR-MKT-007 create, 008); event backbone |
| **2** | Nov–Dec 2026 | Final-I | Simulate & Trade | **M2** calibration, GBM, OU, jump diffusion, Monte Carlo, run statistics (FR-SIM-001..004, 006..008); **M3** strategies, portfolios, cost and slippage, event log, value series, holdings, fills, market and limit orders, exact replay (FR-TRD-001..003, 005..010); **M1** replay playback (FR-MKT-007) and news ingestion (FR-MKT-006); **M7** first projections and SSE progress |
| **3** | Feb–Mar 2027 | Mid-II | Analytics Core | **M5** scenario registry, flash crash, volatility spike, stress runs and breakdowns, concentration (FR-RSK-001, 002, 004..007, 009, 018); full 7-stage TDA pipeline and transitions (FR-RSK-010..017); **M4** model registry, point-in-time feature store, training metadata, FinBERT sentiment, volatility forecast, strategy metrics (FR-ML-001..006) |
| **4** | Apr–May 2027 | Final-II | Explain & Ship | **M6** SHAP, P&L attribution, LLM narration with template fallback (FR-XAI-001, 002, 005); **M7** dashboard views, heatmaps, alert rules, alert log, push delivery, dedup (FR-DSH-001, 002, 005..007, 009); Extended items as time allows; hardening, load tests, end-to-end demo, write-up |

Extended requirements (FR-MKT-005, 010; FR-SIM-005, 009; FR-TRD-004, 011; FR-ML-007..010;
FR-RSK-003, 008; FR-XAI-003, 004; FR-DSH-003, 004, 008) are designed for and built as time
allows, mostly in Iteration 4.

---

## 2. What the Mid evaluation checks, and how Iteration 1 answers it

From the FYP-1 Mid rubric (Form 2, presentation and demo):

| Criterion | Marks | Our evidence |
|---|---|---|
| 3. Live core module with edge and failure cases | **25** | Live demo of M1 ingestion through the gateway: a clean run, then a planted-fault dataset where the cleaning gate rejects bad bars, a re-run that adds zero rows, a viewer blocked from admin actions, an inverted replay session rejected by the database |
| 5. Design artefacts and design evolution | 15 | Updated architecture, ERDs for `platform_db` and `market_db`, ingestion sequence diagram, ingestion-run state diagram, and the design-change log in §6 |
| 1. Proposal actions addressed | 10 | Panel action register with a status and evidence link per item (fill in from the proposal defence feedback) |
| 2. Iteration plan and work breakdown | 10 | This document: owners, dates, status, recovery plan |
| 4. Requirements and acceptance criteria | 10 | Every task below names its FR/NFR and a testable acceptance check |
| 6. Repository, milestones, member evidence | 10 | Branch per task, regular commits from all three members, pull requests, Jenkins history, release tag `v0.1.0` |
| 7. Testing and early validation | 10 | pytest unit and property tests on the cleaning gate, integration tests on real PostgreSQL, frontend tests, all run by Jenkins with published reports |
| 8. Presentation, Q&A, tool ownership | 10 | Each member demos and explains their own module; tool use disclosed |

Form 3 (the written Mid report) additionally needs SRS excerpts with acceptance checks,
design models, setup and implementation documentation, a test plan with early results,
and **full disclosure of external and GenAI tools**. That last item scores zero until it
is disclosed.

**The Mid demo spine** (one connected flow that exercises every Iteration 1 module):

```
admin logs in (M0, JWT)  →  adds instruments (M1)  →  triggers an ingestion run (M1 worker)
  →  cleaning gate passes good bars, rejects planted faults  →  returns and volatility computed
  →  bar.ingested event published (outbox → Redpanda)  →  Market Data page shows bars,
     the run report and rejected rows (frontend → gateway → M1)
failure cases: re-run adds nothing · viewer gets 403 · bad replay window rejected by the DB
```

---

## 3. Iteration 1 tasks

Each task is one `feature/*` branch and one pull request into `develop`. "Done" means
merged, green in Jenkins and deployed to DEV.

### 3.1 Already done

| ID | Task | Owner | Status | Evidence |
|---|---|---|---|---|
| I1-00 | CI/CD: Jenkins, four environments, content-hashed images, smoke tests, rollback, approvals | A | ✅ | `Jenkinsfile`, `ci/`, `docs/ci-cd.md`, PRs #1–#11 |
| I1-01 | Frontend POC imported into `frontend/`, unit tests added | C | ✅ | PR #1, #5 |

### 3.2 Platform foundation (Member A)

| ID | Task | Requirements | Acceptance check | Status |
|---|---|---|---|---|
| I1-10 | **Python workspace:** root `pyproject.toml` (uv workspace), `libs/qs_template` package, shared ruff/mypy/pytest config | NFR-MNT-006 | `uv sync` works from a clean clone; Jenkins Backend CI runs on the template's own tests | ⬜ |
| I1-11 | **Service template core:** settings from environment, structured JSON logs with request id, async SQLAlchemy session, `/health` and `/ready`, error envelope, OpenAPI export | NFR-MNT-001, NFR-OBS-002 | A sample service starts with only environment variables; missing config fails at start-up | ⬜ |
| I1-12 | **Auth in the template:** verify RS256 JWT against the M0 JWKS (cached), `require_role(...)` dependency, user id propagated to logs | FR-PLT-004, FR-PLT-005, NFR-SEC-001 | Expired, forged and wrong-role tokens are rejected in tests; no call to M0 per request | ⬜ |
| I1-13 | **Outbox and consumer:** outbox table and relay to Redpanda, idempotent consumer base with a processed-events table | NFR-REL-007, NFR-REL-008 | State change and event commit together; a redelivered event changes nothing; broker down delays but loses nothing (integration test) | ⬜ |
| I1-14 | **Audit trigger:** reusable migration that installs the before/after audit trigger on chosen tables, append-only by privileges | FR-PLT-006..008, NFR-AUD-001, NFR-INT-005 | Insert, update and delete each produce an audit row; deleted rows stay queryable; the audit table refuses UPDATE | ⬜ |
| I1-15 | **Infrastructure stack in compose:** PostgreSQL 17 + TimescaleDB with one database and one role per service, Redis (queue and cache), Redpanda (dev mode), Traefik routes `/api/<service>` | NFR-MNT-002, NFR-SEC-007 | `qs-dev` runs the whole stack; each service role can reach only its own database | ⬜ |
| I1-16 | **M0 Platform service:** users with a database-level role constraint, Argon2 password hashing, login issuing RS256 JWT, JWKS endpoint, admin create, deactivate, reactivate and change role, events `user.*` | FR-PLT-001..005, NFR-INT-002, NFR-SEC-004 | Admin creates a user who logs in; deactivation makes that user's existing token fail within the token-check window; an unknown role is rejected by the database | ⬜ |
| I1-17 | **Tracing (stretch):** OpenTelemetry in the template, trace id across gateway → service → worker → event | NFR-OBS-001 | One trace shows the full ingestion path | ⬜ |

### 3.3 Market data (Member B)

| ID | Task | Requirements | Acceptance check | Status |
|---|---|---|---|---|
| I1-20 | **`market_db` schema:** instrument, staging bar, bar (hypertable, `NUMERIC` prices, OHLC check constraints), rejected bar, data gap, ingestion run and run item, return series, corporate action, replay session with `end > start` check | FR-MKT-001, NFR-INT-001, NFR-INT-003, NFR-REC-001 | Migrations build the schema from empty in CI (migration check); the database itself refuses `high < low` and an inverted replay window | ⬜ |
| I1-21 | **Instrument master:** admin add, annotate and retire (non-destructive), seed command for the starting universe of about 40 symbols, audited | FR-MKT-001, FR-PLT-006 | Retired instruments stay in history but are no longer ingested; viewers cannot add | ⬜ |
| I1-22 | **Tiingo adapter:** `PriceSource` interface, Redis token-bucket limiter below vendor limits, timeouts, retries with backoff, circuit breaker, recorded responses for tests | FR-MKT-002, NFR-PERF-005, NFR-REL-006 | Tests cover success, empty, 429 with `Retry-After`, 500 then success, malformed JSON, unknown symbol | ⬜ |
| I1-23 | **Cleaning gate:** pandera rules (non-positive prices, OHLC order, duplicates, non-trading days, missing sessions against the exchange calendar, outliers, zero volume), UTC session-close timestamps, reconciliation report (passed, corrected, rejected per rule) | **FR-MKT-011** | Table-driven unit test per rule; property test: the gate never publishes `high < low`; passed + corrected + rejected = input | ⬜ |
| I1-24 | **Ingestion pipeline:** run lock, watermark plus 5-session overlap, staging, gate, idempotent upsert with content hash, vendor corrections as revisions, per-instrument transaction with outbox `bar.ingested` | **FR-MKT-002**, NFR-REL-005, NFR-REL-007 | Re-running a window adds zero rows and zero events; a changed bar creates a revision; two simultaneous runs → one skipped; crash mid-run then re-run gives the same final state | ⬜ |
| I1-25 | **Returns and volatility:** log returns, 20- and 60-day annualised volatility, recomputed from the earliest changed date | FR-MKT-003 | Values match a hand-computed fixture | ⬜ |
| I1-26 | **Scheduling:** Celery worker and single beat, daily run 22:30 UTC, catch-up run 06:00 UTC, admin "run now" and backfill on a low-priority queue | FR-MKT-002, NFR-PERF-004 | Trigger returns 202 within 800 ms; backfill never delays the daily run | ⬜ |
| I1-27 | **Market read API:** instruments, bars, returns, ingestion runs, run report, rejected rows, data quality | FR-MKT-001..003, FR-MKT-011 | Contract exported to OpenAPI; role checks on every endpoint | ⬜ |
| I1-28 | **Planted-fault dataset and demo script:** fixture universe with known defects and the exact expected report | FR-MKT-011 | TEST environment run matches the expected report exactly | ⬜ |
| I1-29 | **Correlation series (stretch):** baskets, rolling correlation matrices in one request, fingerprinted and cached | FR-MKT-004 | One request returns every window's matrix; identical windows return identical fingerprints | ⬜ |
| I1-30 | **Market-environment interface:** published tick-event schema shared by replay and simulation, replay-session create with validation (playback is Iteration 2) | FR-MKT-009, FR-MKT-007 (create), FR-MKT-008 | Schema in `contracts/events/`; an inverted window is rejected by both the API and the database | ⬜ |

### 3.4 Frontend and schemas (Member C)

| ID | Task | Requirements | Acceptance check | Status |
|---|---|---|---|---|
| I1-40 | **Design models for the report:** ERDs for `platform_db` and `market_db`, ingestion sequence diagram, ingestion-run state diagram, generated from or checked against the migrations | Form 3 criteria 5–6 | Diagrams match the merged schema | ⬜ |
| I1-41 | **API client:** TanStack Query, client types generated from each service's OpenAPI with `openapi-typescript`, mocks kept behind `VITE_USE_MOCKS` | NFR-MNT-005 | Changing a backend schema breaks the frontend type check | ⬜ |
| I1-42 | **Real login:** login against M0, token storage, role-aware navigation, logout, expired-session handling | FR-PLT-004, FR-PLT-005 | A viewer never sees admin pages; an expired token returns to login | ⬜ |
| I1-43 | **Instruments page live:** list, add and retire (admin) | FR-MKT-001 | Works against DEV through the gateway | ⬜ |
| I1-44 | **Market Data page live:** bar chart per instrument, ingestion run history, run report and rejected rows | FR-MKT-002, FR-MKT-011, FR-DSH-001 | Shows the planted-fault run's rejections with reasons | ⬜ |
| I1-45 | **Admin users page live:** create, deactivate, change role | FR-PLT-001..003 | Changes show in the audit history | ⬜ |
| I1-46 | **Fix POC duplicate sidebar key** (`/ml/predictions`) | – | No React key warning in tests | ⬜ |

### 3.5 Shared

| ID | Task | Owner | Status |
|---|---|---|---|
| I1-50 | Panel action register: every proposal-defence action with status and evidence link | All | ⬜ |
| I1-51 | Mid report (Form 3): SRS excerpt, design models, implementation and setup, test plan and results, risks, **tool and GenAI disclosure** | All | ⬜ |
| I1-52 | Demo rehearsal: each member presents their own module; run the demo spine and failure cases on TEST | All | ⬜ |
| I1-53 | Promote the Mid build to ACC and PROD and tag `v0.1.0` | A | ⬜ |

---

## 4. Schedule to the Mid

The rubric places the Mid around semester week 8. Dates below assume the evaluation in
the week of **26 October 2026**; adjust once the date is confirmed.

| Week | Dates | Member A | Member B | Member C | Checkpoint |
|---|---|---|---|---|---|
| 1 | 7–13 Oct | I1-10, I1-11, I1-15 | I1-20, I1-22 | I1-41, I1-46, start I1-40 | Stack runs in DEV; schemas migrate in CI |
| 2 | 14–20 Oct | I1-12, I1-13, I1-16 | I1-23, I1-24, I1-21 | I1-42, I1-43 | Login works end to end; one ingestion run lands clean bars |
| 3 | 21–25 Oct | I1-14, I1-17 (stretch), I1-53 | I1-25, I1-26, I1-27, I1-28, I1-30 | I1-44, I1-45, I1-40 | Demo spine passes on TEST; report drafted |
| Mid week | 26 Oct → | I1-52 rehearsal | I1-29 (stretch) | I1-51 final | Demo from TEST (or ACC once a server exists) |

**Critical path:** I1-10 → I1-11 → I1-15 → I1-20 → I1-23 → I1-24 → I1-27 → I1-44. If
anything on it slips, cut in this order: I1-17 tracing, I1-29 correlation, I1-45 admin
page, catch-up run in I1-26. Never cut I1-23 or I1-24; they are the demo.

**Recovery rule:** any task more than three days late gets a named helper and a new date
recorded in this file (rubric criterion 2 rewards a justified, owner-assigned recovery plan).

---

## 5. Decisions to settle before coding

| # | Decision | Recommendation | Affects |
|---|---|---|---|
| D1 | Price storage | `NUMERIC(20,6)` in every database (NFR-INT-001); the tech guide's cleaning sketch uses float and must be updated | I1-20, I1-23 |
| D2 | Vendor corrections to already-published bars | Store a revision and publish `bar.corrected`, not `ON CONFLICT DO NOTHING` | I1-24 |
| D3 | Corporate actions | Store raw and adjusted series (answers the open question in ARC §15) | I1-20, I1-25 |
| D4 | Outliers over 50% | Cross-check with a second vendor; reject if unconfirmed | I1-23 |
| D5 | Instrument universe | About 40 symbols to stay inside Tiingo's free limits | I1-21 |
| D6 | Event backbone | Redpanda (Kafka protocol, a third of the memory) instead of Apache Kafka | I1-13, I1-15 |
| D7 | Gateway authentication | Each service verifies the JWT locally from the JWKS (FR-PLT-004); Traefik only routes and rate-limits | I1-12, I1-15 |
| D8 | Token revocation on deactivation | Short-lived access tokens plus a revocation list in Redis fed by `user.deactivated` | I1-16 |

---

## 6. Design changes since the proposal (for the "design evolution" criterion)

| Proposal | Now | Reason |
|---|---|---|
| Apache Kafka | Redpanda | Same protocol and guarantees in about a third of the memory; fits the free server |
| GitHub Actions (tech guide) | Jenkins, self-hosted | Team-owned build server, approval gates, per-environment locks |
| PostgreSQL 16 | PostgreSQL 17 + TimescaleDB | Current release, supported by TimescaleDB |
| MinIO for cold storage | Cloudflare R2 (cloud), SeaweedFS (local) | Free egress; lighter locally |
| Kubernetes from the start | Docker Compose now, k3s in Iteration 4 | Same images; avoids running a cluster on a laptop during development |
| One gateway authentication check | Gateway routes; every service verifies the JWT itself | Matches FR-PLT-004 and NFR-SEC-001 (authorise where the data lives) |
| Bars upserted once | Revisions with `bar.corrected` | A published bad bar must be correctable downstream (ARC §5.4) |

---

## 7. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Development laptop has little free disk | Docker cannot start; builds fail | Keep 20 GB free; prune images weekly; move ACC/PROD backend to the Oracle server when available |
| Tiingo free-tier limits (50 requests/hour, 500 symbols/month) | Ingestion stalls | Universe of about 40; rate limiter below limits; recorded responses in DEV and TEST |
| Free data licences are non-commercial | Cannot charge users | Fine for the FYP; budget a paid feed before any commercial use |
| No backend server for ACC/PROD | Mid demo runs on the laptop | Demo from TEST; request the Oracle Always Free server early (capacity can take days) |
| One member carries the defence | Form 11 contribution adjustment | Every member owns, commits and demos their own tasks |
| Branch protection not enforced (free private repository) | A direct push could skip checks | Team convention documented in `docs/ci-cd.md`; Jenkins statuses visible on every PR |

---

## 8. After the Mid: rest of the application

| Iteration | Member A | Member B | Member C |
|---|---|---|---|
| 2 (Nov–Dec) | **M3** trading engine: event log, order execution, cost and slippage, projections, rebuild-from-log | **M2** calibration, GBM, OU, jump diffusion, Monte Carlo workers, run statistics; **M1** replay playback with Binance ticks | **M7** first projections and SSE progress; ECharts fan chart, trade-replay view; **M1** news ingestion |
| 3 (Feb–Mar) | Integration harness, sagas, cross-service consistency checks | **M5** TDA pipeline (7 stages), stress scenarios, concentration | **M4** feature store, model registry, FinBERT, volatility forecast, strategy metrics |
| 4 (Apr–May) | k3s deployment, observability dashboards, load tests | Regime detection, evaluation | **M6** SHAP and narration; **M7** alert rules, dedup, push, reports |

Each later iteration gets the same treatment as §3 at its start: tasks, owners,
requirements and acceptance checks.
