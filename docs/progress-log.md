# QuantSim Progress Log

A dated record of what was delivered, decided and found, newest first. Task ids refer
to [iteration-plan.md](iteration-plan.md). Every entry links to the evidence in the
repository or in Jenkins.

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
