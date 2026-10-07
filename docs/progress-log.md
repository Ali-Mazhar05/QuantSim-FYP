# QuantSim Progress Log

A dated record of what was delivered, decided and found, newest first. Task ids refer
to [iteration-plan.md](iteration-plan.md). Every entry links to the evidence in the
repository or in Jenkins.

## 2026-10-07

**Delivered**
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
- Helper commands in `host.sh` ran `rclone` instead of a shell, which silently broke
  link detection and the state check. Found by the hand-over test; fixed before review.
- The tunnel dropped on networks that block QUIC; switched to HTTP/2 over TCP 443.
- An earlier pull request build was aborted after 45 minutes: Docker Desktop had stopped
  because the development laptop's disk was full. Not a pipeline fault; freeing disk
  space and rebuilding fixed it. Recorded as a risk in the plan.

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
