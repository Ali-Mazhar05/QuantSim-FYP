# QuantSim CI/CD: where things stand and what is left (2026-10-10)

This is a hand-over for an agent or teammate taking over the CI/CD setup. Another agent is building the market data service at the same time; §7 says who touches what.

## 1. Ground rules (do not break these)

- **Branch flow:**

  ```
  feature/* → develop (DEV) → test (TEST) → acceptance (ACC, sign-off) → main (PROD, approval, tag)
  ```

  - **Every** change goes through a branch, a pull request and green Jenkins checks before merge.
  - Never commit or push straight to `develop`, `test`, `acceptance` or `main`.
  - Use `bugfix/*` for fixes and `hotfix/*` (from `main`) for production fixes.
- **`develop-poc`:** frozen POC reference. Never modify, rebase or delete it, and never build it.
- **`master`:** stays empty. Never build it.
- **Commit messages:** one basic line, no punctuation, no mention of Claude or AI, and no `Co-Authored-By` line. Example: `Wait longer for Cloudflare Pages before smoke testing`.
- **Merging:**
  - Promotion pull requests (`develop→test`, `test→acceptance`, `acceptance→main`) use "Create a merge commit".
  - Feature pull requests: `docs/ci-cd.md` says squash and the git-flow skill says rebase. This is undecided; ask the user.
- **Cost:** free services only. No paid tiers.
- **GitHub account:** use **Ali-Mazhar05**. A repo-local setting (`credential.https://github.com.username`) overrides the global `awais548`. If `gh` acts as the wrong user, run `gh auth switch -u Ali-Mazhar05`.
- **Approval:** ask the user before any promotion merge or Jenkins approval (acceptance sign-off, production approval).
- **Force-push:** only with `--force-with-lease`, and only on your own feature branch. Never use `--no-verify`.
- **Git-flow skill:** `.claude/skills/quantsim-git-flow/` provides `scripts/preflight.sh` (run before every push) and `scripts/pr.sh` / `scripts/pr.sh promote <from> <to>`. It is on the unmerged branch `feature/git-flow-skill`.

## 2. Repository and machine

- **Repository:** GitHub `Ali-Mazhar05/QuantSim-FYP`, private, free plan. The default branch is `develop`.
- **Remote state:**
  - `origin/develop`, `origin/test` and `origin/acceptance` all point at `85ab2b6` (PR #11 merged).
  - `origin/main` is `fb78c1a` (untouched since August). No tags exist.
  - The local `develop` is stale; fetch first.
- **Laptop:** Windows 11. Git Bash and PowerShell are available. Docker Desktop 29.7.2 is running.
- **Disk:** about 8.8 GB free on C:, which is tight. Low disk has crashed Docker before. Prune build caches after heavy work and never let the disk drop below about 5 GB.
- **Jenkins:** runs locally from the `feature/centralized-jenkins` setup:
  - Containers: `quantsim-jenkins-jenkins-1` (controller) and `quantsim-jenkins-agent-1` (SSH build agent).
  - It is in **quiet mode** (set while the disk was full). Cancel quiet mode once the disk allows.
  - DEV and TEST stacks run as `qs-dev-*` and `qs-test-*`, on http://localhost:8081 and http://localhost:8082.
- **Untracked files in the working tree, never to be committed:**
  - `admin_password`: the Jenkins admin password. Should be removed or git-ignored.
  - `ci/jenkins/.state/`: generated Jenkins security configuration. Should be git-ignored.
  - `FYP_Documentation.pdf`, `QuantSim_Tech_Stack_and_Implementation.md`, `presentation/`: the user's own documents.
  - `services/market/`: draft code the market agent is moving into proper branches.

## 3. How the pipeline works (on `develop`)

There is one declarative `Jenkinsfile` with `agent none`. Every step is a script under `ci/scripts/`.

1. **Prepare:** `plan.sh` maps the branch to an environment and a mode:

   | Branch | Environment | Mode |
   |---|---|---|
   | `develop` | dev | build |
   | `test` | test | promote |
   | `acceptance` | acc | promote |
   | `main` | prod | promote |
   | `hotfix/*` | none | build |
   | anything else | none | ci |

   It also computes a content hash per component from `ci/components.conf`. On `main`, `release-tag.sh check` fails early if `v<VERSION>` already exists.
2. **Checks:**
   - `shellcheck.sh`
   - `frontend-ci.sh`: npm ci, oxlint, tsc, Vitest with coverage, vite build
   - backend checks per `services/*` (and `libs/*` on the template branch): `python-ci.sh` runs ruff, format, mypy and pytest; `migration-check.sh` runs up, down and up on an empty PostgreSQL + TimescaleDB
3. **Build:** in build mode only. Builds an image for each component whose content hash is new and pushes it to GHCR as `ghcr.io/ali-mazhar05/quantsim-<component>:<hash>`.
4. **Promote:** retags existing images (`dev`, `test`, `acc`, `prod`). It fails with "Not built on develop" if an image is missing, and never rebuilds.
5. **Approve production** (`main` only): `input` limited to `RELEASE_APPROVERS`, 24 h timeout.
6. **Deploy:** holds `lock(env-<env>)` while it runs:
   - `make-release.sh`, then `deploy.sh`, then `smoke.sh`.
   - On ACC or PROD, a failure runs `rollback.sh <env> current`.
   - On success, `record-release.sh` records the release and a commit status is posted: `quantsim/dev-verified` or `quantsim/test-verified`.
7. **Acceptance sign-off** (`acceptance` only): an approver's input posts `quantsim/acceptance-signoff`.
8. **Release** (`main` only): tags the images with `v<VERSION>` (`VERSION` is `0.1.0`) and tags the git commit.

**Where things run:**
- DEV and TEST: Docker Compose (`deploy/compose/docker-compose.yml`, projects `qs-dev` and `qs-test`) behind Traefik v3.6, through a read-only docker-socket-proxy.
- ACC and PROD: **frontend only**, on Cloudflare Pages (`pages-deploy.sh`, wrangler 4.148.0). The current project is `quantsim-4hz`; a rename was proposed but not decided.

**Secrets:**
- Files: `deploy/secrets/<env>.enc.env`, SOPS 3.13.3 + age, one recipient (Jenkins). They hold only `SAMPLE_SECRET` so far.
- To give someone decryption access, add their age public key to `.sops.yaml` and run `sops updatekeys`.
- Jenkins credentials are Docker secrets under `ci/jenkins/secrets/`: `admin_password`, `github_app_id`, `github_app_key` (GitHub App `quantsim-jenkins`), `ghcr_user`, `ghcr_token`, `cloudflare_api_token`, `cloudflare_account_id`, `sops_age_key`. The centralized branch adds `r2_access_key_id`, `r2_secret_access_key` and the OAuth app secrets.

**Promotion gate:** GitHub branch protection is unavailable on a free private repo, so the rule is enforced by convention plus `pr.sh promote`, which checks the statuses:

| Merging into | Required status |
|---|---|
| `test` | `quantsim/dev-verified` |
| `acceptance` | `quantsim/test-verified` |
| `main` | `quantsim/acceptance-signoff` |

Full design: `docs/ci-cd.md`.

## 4. What is verified and what is not

| Item | State |
|---|---|
| Pull request checks (frontend, shellcheck) | ✅ PRs #1–#11 green |
| DEV deploy + smoke + `dev-verified` | ✅ 2026-10-07 |
| TEST deploy + smoke + `test-verified` | ✅ 2026-10-07 |
| Automatic rollback | ✅ verified with a deliberately broken release |
| ACC (Cloudflare Pages) | ❌ build #1 failed: smoke test ran before Pages issued the HTTPS certificate. Fix in **open PR #12** (`bugfix/pages-smoke-wait`: 60 × 5 s attempts for Pages). Site later came up at `https://acceptance.quantsim-4hz.pages.dev` |
| Acceptance sign-off | ❌ never posted |
| PROD + `v0.1.0` tag | ❌ never run |
| Backend checks, migration check, backend deploy | ❌ never run on an environment branch (no backend service on `develop` yet) |
| Centralized Jenkins (agent split, host.sh hand-over, Oracle setup, GitHub sign-in, backups) | 🔄 built and partly tested on `feature/centralized-jenkins`, unmerged, no PR |
| Oracle server, DuckDNS name, GitHub OAuth app | ❌ not provisioned |
| Vercel app posting statuses on the repo | ⚠ not part of the design; user to decide keep or disconnect |

## 5. Unmerged branches (local, not pushed unless noted)

| Branch | Content | Notes |
|---|---|---|
| `bugfix/pages-smoke-wait` | Pages smoke wait | **Pushed, PR #12 open** |
| `feature/git-flow-skill` | git-flow skill (`preflight.sh`, `pr.sh`) + docs note that feature PRs are rebase-merged | 2 commits |
| `feature/iteration-plan` | `docs/iteration-plan.md`, `docs/progress-log.md`, `docs/ingestion-plan.md` | docs only |
| `feature/centralized-jenkins` | CasC split (`casc/jenkins.yaml`, `casc/security/{local,github}.yaml`), SSH build agent (controller has 0 executors, Jenkinsfile uses `agent { label 'docker' }`), `host.sh` + `lease.sh` (R2 hand-over, 2-min lease), `team-accounts.sh` (`secrets/team_users` lines `user:password:role`, roles admin/approver/developer), `init-env.sh`, `compose.server.yml` + `Caddyfile`, `bootstrap-server.sh`, `backup.sh` | 10 commits, about 22 files |
| `feature/service-template` | uv workspace, `libs/qs_template` (config, logging, errors, health, DB, JWT/JWKS auth, revocation, outbox, idempotent consumers, Redpanda, audit), `python-ci.sh` with DB/Kafka markers, Backend CI covers `libs/*` | 7 commits |
| `feature/platform-service` | M0 Platform service (stacked on the template) and the compose stack: postgres + db-init (`timescale/timescaledb:2.22.1-pg17`), redis 8.2, redpanda v25.2.9, platform, platform-relay, platform-migrate; `platform` line in `ci/components.conf` | 12 commits. **Must stay a draft PR until its DEV/TEST secrets exist** (§6 step 6) |
| `feature/spec-tooling` | OpenSpec + BMAD + analyst personas | 3 commits |
| `feature/market-user-stories` | stacked on spec-tooling; Iteration 1 PRD under `docs/bmad/` | in progress (market agent) |
| `feature/document-branch-protection`, `feature/market-ingestion`, `backup-pre-rewrite` | older or backup | leave alone; ask before deleting |

**Suggested merge order**, one PR at a time, each green in Jenkins before the next:
1. PR #12
2. `feature/git-flow-skill`
3. `feature/iteration-plan`
4. `feature/centralized-jenkins`
5. `feature/service-template`
6. `feature/platform-service` (once secrets exist)
7. `feature/spec-tooling`

## 6. What needs to be done (CI/CD scope)

In priority order. Each step is its own branch and PR.

1. **Housekeeping:** git-ignore `admin_password` and `ci/jenkins/.state/`, and check that neither appears in git history. Cancel Jenkins quiet mode if the disk allows (at least 5 GB free after pruning).
2. **Merge PR #12.** Then re-run the `acceptance` build. Expected result: ACC deploys, the smoke test passes, and a pipeline approver signs off (ask the user first). `quantsim/acceptance-signoff` should appear on the commit.
3. **Merge `feature/git-flow-skill` and `feature/iteration-plan`.** Before the iteration-plan merge, update `docs/iteration-plan.md` so it agrees with the decisions:
   - I1-26 uses a PostgreSQL job queue, not Celery.
   - I1-23 uses pure Python with decimals, not pandera.
   - Prices are `NUMERIC(23,8)`.
   - D4 is "flag outliers, configurable to reject".
4. **Merge `feature/centralized-jenkins`.** Verify:
   - the agent runs builds and the controller has no Docker;
   - anonymous access gets 403;
   - `host.sh status|start|stop` works and the lease refuses a second host.
5. **Oracle Cloud Always Free CI server**, when the user has the account:
   - **VM:** Canada Southeast (Toronto), `VM.Standard.A1.Flex`, 2 OCPU / 12 GB, Ubuntu 24.04, 100 GB boot volume. Ingress TCP 80/443 and UDP 443.
   - **DNS:** the user picks a free DuckDNS name; the plan assumed `quantsim-ci`, since `quantsim` is taken. It gives `ci.`, `dev.` and `test.` hosts.
   - **GitHub OAuth app:** callback `https://ci.<name>.duckdns.org/securityRealm/finishLogin`.
   - **GitHub App webhook:** `https://ci.<name>.duckdns.org/github-webhook/`.
   - **Bootstrap:** run `bootstrap-server.sh` as root, then `init-env.sh --server --domain <name>.duckdns.org --email … --approvers "Ali-Mazhar05,<teammate>"`. Ask the user for teammates' GitHub usernames and who approves.
   - **Multi-arch:** set `QS_PLATFORMS=linux/amd64,linux/arm64`. The server is ARM.
   - **Idle reclaim:** Oracle may reclaim Always Free VMs idle for 7 days.
6. **Per-environment secrets for the backend.** Without these the platform and market deploys cannot run. Add them to `deploy/secrets/{dev,test}.enc.env` with SOPS:
   - Platform:
     - `QS_SIGNING_KEY` and `QS_SIGNING_KEY_ID`; generate with `qs-platform generate-signing-key`
     - `QS_BOOTSTRAP_ADMIN_PASSWORD`
     - DB and Redis passwords, matching `db-init` and the compose file
   - Market, needed by the market branches:
     - `TIINGO_API_KEY`: the user registers a free Tiingo account
     - `MARKET_DB_PASSWORD`
   - Then `feature/platform-service` can leave draft.
7. **Backend in the pipeline:** after `service-template` and `platform-service` merge, confirm on a real run that:
   - Backend CI and the migration check run;
   - the `platform` image builds;
   - `platform-migrate` runs before `platform` starts, and a failed migration stops the deploy;
   - the smoke test passes on `/api/platform/health` with the content hash.
8. **First release `v0.1.0`:** promote `develop → test → acceptance → main`. Each promotion needs the user's go-ahead. Expected end state: PROD on Pages serves the TEST-verified frontend hash, and tag `v0.1.0` exists. Backend on ACC/PROD is **Could**-tier: it needs the Oracle server, `COMPOSE_TARGET=ssh://deploy@<server>`, a `deploy-ssh` credential and an `sshagent` wrapper around Deploy.
9. **Decisions to put to the user:**
   - feature PR merge method (squash or rebase)
   - keep or disconnect the Vercel integration
   - the Pages project rename
   - whether ARC's `/v1/` URL prefix is adopted (affects the smoke test paths)

The requirements behind this work are FR-1 to FR-13 in `docs/bmad/planning-artifacts/prds/prd-QuantSim-2026-10-10/prd.md` (branch `feature/market-user-stories`). Priority tiers are in §8.1. Must: FR-1, 2, 3, 8, 9, 13. Should: FR-4 to FR-7 and FR-11. Could: FR-10 webhook, FR-12 backup, backend on ACC/PROD.

## 7. Coordination with the market agent

| Area | Owner |
|---|---|
| `Jenkinsfile`, `ci/` (scripts, jenkins, components.conf except the `market` line), `deploy/env/`, `deploy/secrets/` (values), `.sops.yaml`, `docs/ci-cd.md` | **CI agent** |
| `services/market/`, `libs/qs_template/` fixes, `docs/bmad/`, `openspec/`, `contracts/events/` | **Market agent** |
| The `market` line in `ci/components.conf`; `market*` services in `deploy/compose/docker-compose.yml`; the `market` DB and role in `db-init` | Market agent proposes them in its `feature/market-deployment` PR; the CI agent reviews |

- The market agent works in a **separate git worktree** and stacks its branches on `feature/platform-service`. Do not rebase or force-push `feature/service-template` or `feature/platform-service` without telling the user, because the market branches depend on them.
- The market agent's PRs need Jenkins online to get checks. Keep Jenkins out of quiet mode once the disk allows.
