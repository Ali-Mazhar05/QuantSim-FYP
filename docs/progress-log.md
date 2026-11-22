# QuantSim Progress Log

A dated record of what was delivered, decided and found, newest first. Task ids refer
to [iteration-plan.md](iteration-plan.md). Every entry links to the evidence in the
repository or in Jenkins.

## 2026-11-22

**Delivered (Iteration 2, contract K6, `feature/k-k6-metrics` into `develop`)**
- **Metrics library (K6):** `libs/qs_quant` with total return, annualised volatility,
  Sharpe, max drawdown, turnover and historical VaR/CVaR (Lane C guide §7.6). Fixture
  values match an exact rational reference to 1e-12; 200-example property tests (scale
  invariance, max drawdown in [0, 1], CVaR >= VaR, determinism); each function under
  50 ms on 10,000 points; purity check; 100% line coverage. Consumers: A16 run metrics
  (Lane A) and B16 Monte Carlo VaR/CVaR (Lane B). The trading, simulation and risk images
  now rebuild when the library changes (`ci/components.conf`).

## 2026-11-20

**Delivered (Iteration 2, Lane A, through `lane/a-trading` into `develop` by #99 and #102)**
- **Trading engine interfaces (A00, #81):** orders, cost and slippage models, strategy and
  history-only view, versioned trade-log payloads, the market-environment port.
- **Execution (A11, #87):** next-open market fills, limit gap/cross/expiry, cash and
  position checks at placement and at fill, fixed + per-share + percentage costs, fixed-bps
  and volume slippage (ADR 04).
- **Strategies (A12, #88):** buy and hold, MA crossover, momentum with a max-position cap,
  mean reversion, on a history-only view that raises on look-ahead (ADR 05).
- **trading_db (A13, #89):** append-only, hash-chained `trade_event` hypertable (guard
  trigger for every role, UPDATE/DELETE/TRUNCATE revoked, seq unique and gap-free across
  chunks), environment-binding CHECK, projection tables.
- **Engine job (A14, #92):** one transaction per session, outbox, crash resume that must
  recompute the stored hash before writing, `engine.run` on the K1 queue.
- **Projections and rebuild (A15, #96):** one fold for live writes and rebuild, chain
  verification, state as of any seq, `verify` and `rebuild [--apply]` commands.
- **Trading API (A16, #97, #100):** strategies, portfolios, idempotent run submit, run
  status, paged events, fills, holdings, value series, state, verify, admin rebuild,
  metrics (return, volatility, Sharpe and drawdown wait for Lane C's K6).
- **CI:** Windows-host fixes (A01, #83), tunnel restart (#52), lane pull requests and
  Playwright gates (A22, #84), Playwright DEV smoke gating TEST (A21, #91), checkout retry
  (#90) and a git mirror on the build agent (#93), trading live check on every DEV deploy
  (#101).
- **Release v0.1.2** promoted develop → test → acceptance → main (#94, #95, #98) with ACC
  sign-off and production approval; tagged at `6d79b46`.

**Found and fixed**
- The lab PC reaches GitHub at about 11 KiB/s, so full clones hit the 10-minute checkout
  timeout and every build failed before running code. Checkouts now borrow from a mirror on
  the agent's volume (#93).
- A trading API test shared its database with the role-matrix test, whose older queued runs
  the worker claimed first; the run test now uses its own database (#97).

**Verified**
- DEV deploy of `508f720`: Playwright `dev-smoke` 3/3 against the real site, then the
  trading live check: a portfolio on the bundled demo environment ran all sessions in 2 s,
  26 events with an intact hash chain, and fills, value series, state, verify, holdings,
  metrics and an admin rebuild (`identical`) all ended on the run's final hash.
- Trading db tests on TimescaleDB in Jenkins: 58/58, including crash after sessions 1, 5
  and 9 then resume to an identical log.

**Decided**
- ADR 04 (execution timing), ADR 05 (strategy type) and ADR 09 (service tokens) recorded
  in `docs/adr/`. Confirms ADR 08 for Lane A: a symbol with no bar on a session has no
  tick, and the engine tolerates it.

## 2026-11-18

**Delivered**
- **Platform kit:** job queue library with leases and idempotent submit (K1, #73); service
  scaffold that generated the simulation, trading and risk services (K2, #74); smaller DEV
  footprint (#76). The three new services answer `/health` on DEV.
- **Accounting core** with Decimal money, average cost and P&L (A10, #75).
- Executable market smoke test and a CI check for script modes (#72).

**Found and fixed**
- The shared CI cache volume held root-owned files from a local deploy, so `npm ci` failed
  in every build; ownership returned to the Jenkins user.

**Decided**
- Jenkins and every environment's stack moved to the always-on Linux lab PC.

## 2026-11-14

**Found and fixed (same branch)**
- The sign-up route records the new account itself as the acting user, so the audit feed
  showed self sign-ups as invitations. Invitations are now credited to the admin who sent
  them, sign-ups to the new account, and accounts created already verified by
  `bootstrap-admin` and `seed-test-users` to System. Covered by platform tests.
- The chart's screen-reader line was positioned against the whole page and caused a
  page-wide horizontal scrollbar on pages with a chart; it is now anchored in the chart.

**Verified**
- Rebuilt the local stack from empty, with one clean Tiingo backfill: all 40 instruments
  succeeded (BRK.B included), 119,400 bars from 2015-01-02 to 2026-11-13, 0 rejected.
  Jenkins' own scripts: template 99, platform 107, market 323, frontend 88 tests, lint,
  type check, build and migration check, all green. Role walkthrough PDF regenerated
  (20 pages, including the chart axes and hover).

## 2026-11-13

**Delivered (branch `feature/iteration1-prototype-integration`, not yet merged)**
- **Iteration 1 prototype integration**, keeping the prototype as the source of truth (no
  layout changes). Market Environments, Create Market Environment, the top bar, the Replay
  header and chart, the Audit Log and the System page now show real data. Buttons follow
  the capabilities the platform returns from `/auth/me`, so the UI never offers what the
  backend would refuse (I1-42, I1-43, I1-44).
- **Market environments API** (`GET/POST /api/market/environments`, `GET /{id}`):
  quant and admin create, everyone reads. An inverted window is refused by the API (422)
  and by the database CHECK (FR-MKT-008). Status is `ready` when every instrument has data
  in the window, otherwise `draft`. Migration `0003` audits the table.
- **Audit feeds** (`GET /api/platform/audit`, `GET /api/market/audit`, admin only), in one
  row shape the Audit Log page merges. They cover sign-ins, invitations, approvals, role
  changes and deactivation; instrument and environment changes; and ingestion runs. A run
  that rejected bars or partly succeeded is a warning; a failed run is critical
  (FR-PLT-006..008).
- **Candlestick chart:** a fixed price scale, a date axis, a hover tooltip (open, high, low,
  close, change, volume) and keyboard reading. Used on Market Data, Create Market
  Environment and Replay.

**Found and fixed**
- Rebased commits on `develop` had dropped earlier work. `c2d858a` unmounted the
  ingestion-run routes (404 when deployed). `898f451` removed the scheduler settings, so
  `market-scheduler` would crash on TEST. `be4bf02` and `7c8770f` removed market README
  sections. All restored, with the route-role matrix test covering the run routes again.
- Tiingo refuses `BRK.B` (404) and serves `BRK-B`; the adapter now converts class shares.
  Found by a real backfill and verified live.
- The Audit Log credited command-line changes to the affected user. A change with no
  recorded actor is now shown as System, except actions only the account holder can take.

**Verified**
- Jenkins' own scripts, run locally: template 99, platform 106, market 323 tests (118
  real-data tests skipped by design), market migration up/down/up, frontend lint, type
  check, 88 tests and build.
- The real stack, run locally with 119,360 real Tiingo bars for all 40 instruments
  (2015-01-02 to 2026-11-12, 0 gaps, 0 rejected, 2 flagged as outliers). Clicked through
  as viewer, analyst, quant and admin. The backend refused each role exactly as the role
  matrix says (403/401), and accepted calls failed only on deliberately invalid bodies (422).
  Evidence: the role walkthrough PDF with screenshots.

**Decided**
- Replay playback (Play/Pause) moves to Iteration 2 with FR-MKT-007.
- Next for the integration: OpenAPI-generated frontend types with contract checks in
  Jenkins (I1-41), the remaining unit-test gaps, then Playwright tests against DEV gating
  promotion to TEST.

**Known limits**
- DEV uses recorded vendor data (AAPL Jan–Feb 2024, NVDA May–Jun 2024), so most
  instruments show no price there, and environments made from the UI (window 2025-01-01 to
  2026-06-30) are draft. TEST, on Tiingo, shows real data.
- A full 40-instrument backfill on TEST takes about 8 hours with the normal request reserve
  (5 manual or backfill requests an hour).

## 2026-10-14

**Decided**
- **Ingestion plan revised** ([ingestion-plan.md](ingestion-plan.md), section 0 and
  decisions D10 to D15):
  - the gap grace period is close plus 12 hours, matching the built gate, not one hour;
  - scheduled runs are enabled on TEST only and share one Tiingo budget per API key;
  - until an always-on host exists, "ten days of scheduled runs" becomes at least three
    scheduled runs plus a manual-run log;
  - correlation (FR-MKT-004) is its own stretch work item, moving to Iteration 3 if cut;
  - one shared `TIINGO_API_KEY` goes into the encrypted secrets, and its real limits are
    verified by a one-symbol vendor check before the adapter is trusted.

**Found**
- The four open market pull requests (#14, #18, #31, #15) still target branches that are
  already merged, and #14 and #18 carry red statuses from earlier runs on a laptop host.
  They are re-pointed at `develop` and merged in order before new market work starts.
- The Tiingo adapter, instrument master, run worker, scheduler, read API and deployment
  of the market service are not built yet. Only the schema, calendar, cleaning gate,
  returns and ERD are.

## 2026-10-12

**Delivered**
- **CI/CD module complete.** Every environment deploys from its branch: DEV and TEST
  automatically, ACC with an approver's sign-off and PROD with an approver's approval,
  each skippable per environment with `AUTO_APPROVE` in `deploy/env/acc.env` and
  `deploy/env/prod.env`.
- **All four websites on Cloudflare Pages**, DEV and TEST included, at fixed addresses
  that stay up whoever hosts Jenkins.
- **Shared laptop hosting** (`ci/jenkins/host.sh`): a host lease and Jenkins' state in
  Cloudflare R2, a public Jenkins link, a dedicated build agent, per-person logins with
  GitHub usernames; Ali-Mazhar05 admin, AfnanRizwan1 and SaintOfAllOranges approvers.
- **Host housekeeping**: a sweep after every build (leftover test containers and volumes,
  build cache), test containers that no longer leak volumes, short test container names
  for long branch names, `ci/jenkins/compact-docker-disk.ps1`.
- **Team guide**: [ci-cd-team-guide.md](ci-cd-team-guide.md).

**Verified**
- Frontend through every environment: v0.1.0 released to PROD on 2026-10-11 with the
  ACC sign-off and PROD approval, one image built once and promoted unchanged.
- Backend on DEV and TEST: Backend CI (111 tests), the migration check, the `platform`
  image built once on `develop`, `platform-migrate` before the new version, smoke test on
  `/api/platform/health` with the content hash, the same image promoted to TEST.
- Hotfix: `hotfix/favicon-link` from `main`, built on its branch, approved and released to
  PROD as v0.1.1, then merged back into `develop`.
- Hand-over: an empty second Jenkins restored the full history from R2 and continued the
  build numbers; a second host was refused while the lease was held.

**Decided**
- Laptop hosting instead of Oracle Cloud (card verification failed); the CI server
  setup stays in `ci/jenkins/` for later.
- Every pull request, feature and promotion alike, merges with a merge commit.
- The Vercel integration stays; its checks are informational.

**Known limits**
- Backend runs on DEV and TEST only, and only while someone hosts Jenkins; ACC and PROD
  serve the frontend until an always-on server exists.
- On the host laptop Docker's disk file must be compacted now and then, and Docker's
  memory capped with `.wslconfig`.

## 2026-10-09

**Delivered (committed, tests pending)**
- **I1-16 Platform service (M0)** on `feature/platform-service`: users with a database
  role constraint, Argon2id passwords, sign-in with lockout and uniform failure responses,
  RS256 tokens and a JWKS endpoint with key rotation, admin user management, deactivation
  and role changes that revoke existing tokens everywhere, a last-admin guard that holds
  under concurrent requests, events through the outbox, per-user audit history, Alembic
  migrations, container image, first-admin bootstrap. 30 API and unit tests written.
- **I1-15 Deployment stack**: PostgreSQL + TimescaleDB with one database and role per
  service, Redis with append-only persistence, Redpanda, the Platform API, relay and
  migration containers, all on an internal network behind the gateway.
- **Audit trail** can exclude secret columns; password hashes never reach the log.
- **Jenkins team accounts** (`feature/centralized-jenkins`): each member gets their own
  login and role (admin, approver, developer) on whichever laptop hosts Jenkins, from
  `secrets/team_users`; approvers become the release approvers automatically.

**Blocked**
- The development laptop is down to about 1 GB free and Docker Desktop has stopped
  responding, so the new tests, the lockfile update, the per-environment secrets for the
  stack and the Jenkins configuration cannot be run or verified. These run first once
  space is freed; nothing is pushed until they pass.

## 2026-10-07

**Delivered**
- **I1-10 – I1-14 Shared service template (`feature/service-template`, 9 commits, 75
  tests).** The uv workspace and `libs/qs_template`, which every backend service builds
  on:
  - configuration from `QS_*` environment variables that fails fast when incomplete;
    structured JSON logs with request id and user; RFC 9457 problem-details errors that
    never leak internals; `/api/<service>/health` (with the build's content hash for the
    smoke test) and `/ready` (database and dependency checks, 503 while one fails);
    async database sessions that commit or roll back as a unit
  - authentication: RS256 tokens verified in every service against the Platform
    service's public keys (cached, rotation-aware, protected against refetch floods,
    fail closed), role checks, and a shared Redis revocation list so deactivation and
    role changes cut off existing tokens everywhere (FR-PLT-002..005)
  - transactional outbox, idempotent consumers and Redpanda adapters with retries and a
    dead-letter topic (NFR-REL-007, NFR-REL-008, NFR-OBS-003)
  - database audit trail with before/after state, acting user and request id, deleted
    rows kept, log refuses UPDATE, DELETE and TRUNCATE (FR-PLT-006..008, NFR-INT-005)
  - Backend CI now covers `libs/` too and starts a throwaway PostgreSQL + TimescaleDB
    and Redpanda for tests that need them
- **I1-02 Centralised CI (in review, `feature/centralized-jenkins`).**
  - Builds moved off the Jenkins controller onto a dedicated SSH build agent container;
    the controller no longer has Docker access.
  - Any team member can host Jenkins in turn (`ci/jenkins/host.sh start | stop |
    status`). Job history, build numbers and recorded releases are handed over through
    Cloudflare R2; a host lease refreshed every 2 minutes stops two machines running
    Jenkins at once; DEV and TEST are redeployed on the new host from the same images; a
    free tunnel gives the team a link to the current host.
  - Always-on CI server setup for Oracle Cloud Always Free: Caddy with Let's Encrypt
    HTTPS, GitHub sign-in limited to team members, webhooks, `linux/arm64` and
    `linux/amd64` images, `bootstrap-server.sh`, nightly `backup.sh` with optional R2
    copy.
- **Iteration plan** (`docs/iteration-plan.md`): every iteration mapped to requirements,
  Iteration 1 split into owner-assigned tasks with acceptance checks, ordered by
  dependency rather than by date.
- **Branch protection limitation documented** (`docs/ci-cd.md`): not enforced on a free
  private repository, followed by team convention instead.

**Verified**
- Pipeline on the new build agent: green in 2 min 13 s (ShellCheck, lint, type check,
  8 frontend tests, build).
- Deploy and smoke test from inside the agent: secrets decrypted, stack healthy,
  content hash confirmed.
- Shared hosting hand-over between two simulated laptops: second host refused while the
  first held the lease; state (job, recorded release) restored on a wiped machine;
  restart on the same host skipped the download; forced takeover works.
- Public tunnel link reaches Jenkins; anonymous access refused (HTTP 403).
- Backup archive 780 KB after excluding workspaces, caches and plugins (was 222 MB).
- GitHub sign-in configuration loads and redirects to GitHub; Caddy configuration valid.

**Found and fixed**
- asyncpg runs one SQL statement per call, which would also break Alembic migrations;
  the audit installer now ships as single statements.
- A Python helper inserted control characters into a shell script while editing it;
  caught by review and removed.
- Helper commands in `host.sh` ran `rclone` instead of a shell, which silently broke
  link detection and the state check. Found by the hand-over test; fixed before review.
- The tunnel dropped on networks that block QUIC; switched to HTTP/2 over TCP 443.
- An earlier pull request build was aborted after 45 minutes: Docker Desktop had stopped
  because the development laptop's disk was full. Not a pipeline fault; freeing disk
  space and rebuilding fixed it. Recorded as a risk in the plan.

**Risk raised**
- The development laptop's disk is nearly full (about 2 GB free). Docker Desktop has
  already failed to start once for this reason; the infrastructure stack and service
  images need roughly 5 GB more. Freeing space, or moving builds to the free Oracle
  server, is now on the critical path.

**Decided**
- Laptop hosting rotates between members until an always-on server exists; the free
  Oracle Cloud server remains the target.

## 2026-10-06

**Delivered**
- **I1-00 CI/CD** (PRs #1–#11, merged into `develop`).
  - Self-hosted Jenkins 2.580.1 LTS with configuration as code and pinned plugins.
  - One `Jenkinsfile` for every branch: ShellCheck, frontend lint, type check, tests with
    coverage and build; backend checks and migration checks that switch on as services
    are added.
  - Images tagged by content hash, built once on `develop` and promoted unchanged to
    TEST, ACC and PROD; DEV and TEST on Docker Compose behind Traefik; ACC and PROD
    frontend on Cloudflare Pages.
  - Smoke tests that check the deployed content hash, automatic rollback on ACC and
    PROD, approval gates, commit statuses that gate promotion, release tagging.
  - SOPS-encrypted secrets per environment.
- **I1-01 Frontend** imported from `develop-poc` into `frontend/` with its full commit
  history; first unit tests (8) added; container image with health and version
  endpoints.
- Branch flow set up: `feature/*` → `develop` → `test` → `acceptance` → `main`;
  `develop-poc` frozen as the POC reference; `master` left empty.

**Verified**
- DEV deployed by Jenkins and serving the POC at localhost:8081.
- TEST environments isolated from DEV on the same host (each gateway routes only its own
  project's containers).
- A deliberately broken release failed its smoke test and was rolled back automatically.

**Decided**
- Jenkins over GitHub Actions (self-hosted) and over Woodpecker (no approval step inside
  a pipeline, no per-environment lock).
- ACC and PROD frontend on Cloudflare Pages (free, no domain needed); backend on Oracle
  Cloud Always Free when available.
