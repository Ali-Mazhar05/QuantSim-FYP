# QuantSim CI/CD

How code moves from a feature branch to production, what the pipeline checks, and how
to operate it. The pipeline is a self-hosted Jenkins (`ci/jenkins/`) running one
`Jenkinsfile`; every step it runs is a script in `ci/scripts/` that also runs on a laptop.

## Branches and environments

```
feature/*  ──PR──▶  develop  ──PR──▶  test  ──PR──▶  acceptance  ──PR──▶  main
 checks only         DEV               TEST           ACC                 PROD
                     build images      promote        promote             approve, promote
                     deploy            deploy         deploy, sign-off    deploy, release tag

develop-poc   the original POC, kept as a frozen reference; never built
master        left empty; never built
hotfix/*      branched from main, checked and built, merged into main and back into develop
```

| Environment | Branch | Where it runs | Address |
|---|---|---|---|
| DEV | `develop` | Jenkins host, compose project `qs-dev` | http://localhost:8081 |
| TEST | `test` | Jenkins host, compose project `qs-test` | http://localhost:8082 |
| ACC | `acceptance` | Cloudflare Pages, branch `acceptance` | `https://acceptance.<project>.pages.dev` |
| PROD | `main` | Cloudflare Pages, production branch | `https://<project>.pages.dev` |

Each environment's settings live in `deploy/env/<env>.env`. ACC and PROD currently host
only the frontend; backend services join them once a server exists (see
[Moving ACC and PROD to a server](#moving-acc-and-prod-to-a-server)).

## What the pipeline does

| Stage | Runs on | What happens |
|---|---|---|
| Prepare | every build | Works out the environment and mode for the branch, computes each component's content hash, checks which images already exist (`plan.sh`). On `main`, fails early if `VERSION` is already released |
| Pipeline scripts | every build | ShellCheck on `ci/scripts/` |
| Frontend CI | every build | `npm ci`, `oxlint`, `tsc`, Vitest with coverage, `vite build`. Test and coverage reports are published in Jenkins |
| Backend CI | every build with services | For each `services/<name>`, in parallel: `ruff`, `ruff format --check`, `mypy`, `pytest`, then the migration check: upgrade to head, downgrade to base, upgrade again, on an empty PostgreSQL + TimescaleDB |
| Build images | `develop`, `hotfix/*` | Builds and pushes only the components whose content hash is new |
| Promote images | `develop`, `test`, `acceptance`, `main` | Points the environment tag (`dev`, `test`, `acc`, `prod`) at the image built on develop. Fails if it was never built there |
| Approve production | `main` | Waits up to 24 hours for an approver. Holds no executor while waiting |
| Deploy | environment branches | Writes the release file, decrypts secrets, deploys, smoke tests, records the known-good release. ACC and PROD roll back automatically on failure. Holds the `env-<name>` lock so two deploys never overlap |
| Acceptance sign-off | `acceptance` | An approver checks ACC and accepts or rejects it |
| Release | `main` | Tags the images and the commit `v<VERSION>` |

### Commit statuses that gate promotion

Jenkins posts these on the commit it verified. Branch protection requires them on the
promotion pull request, whose head is that same commit.

| Status | Posted when | Required to merge into |
|---|---|---|
| `quantsim/dev-verified` | DEV deployed and passed its smoke test | `test` |
| `quantsim/test-verified` | TEST deployed and passed its smoke test | `acceptance` |
| `quantsim/acceptance-signoff` | An approver accepted ACC (a rejection posts a failure) | `main` |

## How images are versioned

Every component in `ci/components.conf` lists the paths that define it. Its image tag is
a short hash of the git content of those paths (`content-hash.sh`), for example
`ghcr.io/ali-mazhar05/quantsim-frontend:d6b01f55817f`.

- A promotion merge produces a new commit but the same content, so the same hash: the
  image is reused, never rebuilt. TEST, ACC and PROD run exactly what DEV ran.
- A change that does not touch a component leaves its hash, and its image, alone.
- Every image carries `/version.json` (frontend) or a health endpoint reporting its
  content hash, so the smoke test proves the environment serves the build just deployed.
- Moving tags (`dev`, `test`, `acc`, `prod`) and release tags (`v0.1.0`) are added on top;
  the hash tag never changes.

## Everyday work

### Ship a change
1. Branch from `develop`: `feature/<short-name>`.
2. Push; Jenkins runs the checks. Open a pull request into `develop`; it needs the Jenkins
   check and one review. Squash merge.
3. Jenkins builds, deploys DEV and posts `quantsim/dev-verified`.

### Promote
Open a pull request `develop → test` (then `test → acceptance`, then `acceptance → main`)
and merge it with **Create a merge commit**. The required status from the previous
environment must be green first.

### Approve
Open the running build in Jenkins (Pipeline Graph view) and answer the input step.
Only users listed in `RELEASE_APPROVERS` (`ci/jenkins/casc.yaml`) can approve.

### Release a new version
Bump `VERSION` in a pull request into `develop` and promote as usual. `main` refuses to
deploy a version that is already tagged.

### Hotfix
Branch `hotfix/<name>` from `main`, open a pull request into `main`, and after release
merge `main` back into `develop`.

### Roll back by hand
From the Jenkins container:

```bash
docker compose -f ci/jenkins/compose.yml exec jenkins bash
cd /var/jenkins_home/workspace/<a checkout of the repository>
ci/scripts/rollback.sh <env> previous   # the release before the current one
```

Recorded releases are in `/var/jenkins_home/releases/<env>/`.

### Change a secret
Secrets are SOPS-encrypted per environment in `deploy/secrets/<env>.enc.env`.

```bash
sops deploy/secrets/dev.enc.env        # opens the decrypted file in your editor
```

To let a team member edit secrets, add their age public key to `.sops.yaml` and run
`sops updatekeys deploy/secrets/<env>.enc.env` for each environment.

### Run the pipeline steps locally
The scripts need only bash, git and Docker. `QS_LOCAL=1` keeps images in the local
Docker daemon instead of the registry.

```bash
ci/scripts/frontend-ci.sh
ci/scripts/python-ci.sh market
export QS_LOCAL=1 IMAGE_PREFIX=quantsim
ci/scripts/build-push.sh frontend
ci/scripts/make-release.sh dev .ci/release.env
ci/scripts/deploy.sh dev .ci/release.env      # needs SOPS_AGE_KEY_FILE
ci/scripts/smoke.sh dev .ci/release.env
```

## Adding a backend service

The pipeline picks services up without editing the `Jenkinsfile`. A service in
`services/<name>/` must provide:

| Requirement | Used by |
|---|---|
| `pyproject.toml` with a uv lockfile; `ruff`, `mypy` and `pytest` in the dev group; at least one test | `python-ci.sh` |
| `alembic.ini` whose `env.py` reads `DATABASE_URL` (`postgresql+asyncpg://...`), if it owns tables | `migration-check.sh` |
| `Dockerfile` taking build args `VERSION`, `CONTENT_HASH`, `GIT_SHA`, `BUILD_TIME` | `build-push.sh` |
| `GET /api/<name>/health` returning 200, ideally with `"content_hash"` in its JSON | `smoke.sh` |

Then:
1. Add a line to `ci/components.conf` listing its Dockerfile, build context and the paths
   that define it (its folder, `libs/qs_template`, the lockfile).
2. Add the service, and a `<name>-migrate` one-off container in the `migrate` profile, to
   `deploy/compose/docker-compose.yml` (a commented example is in the file).
3. Add its secrets to `deploy/secrets/<env>.enc.env`.

## Moving ACC and PROD to a server

When the Oracle Cloud (or Hetzner) server exists:
1. Create a `deploy` user that can run Docker, with SSH key login only; open ports 22,
   80 and 443.
2. Add the `ssh-agent` plugin to `ci/jenkins/plugins.txt`, add the private key as a
   `deploy-ssh` credential in `casc.yaml`, and wrap the Deploy stage's steps in
   `sshagent(['deploy-ssh'])`.
3. In `deploy/env/acc.env` and `prod.env` set `COMPOSE_TARGET=ssh://deploy@<server>` and
   `SMOKE_BASE_URL` to the server's address.
4. If the server is ARM, set `PLATFORMS=linux/amd64,linux/arm64` for image builds.

## One-time setup

1. **Jenkins:** follow `ci/jenkins/README.md` and `ci/jenkins/secrets/README.md`.
2. **Branches:** `develop` from `main`, then `test` and `acceptance` from `develop`.
3. **GitHub repository settings:** default branch `develop`; protect `develop-poc` from
   deletion and force pushes; protect the four environment branches:

   | Branch | Required checks | Reviews | Up to date | Linear history |
   |---|---|---|---|---|
   | `develop` | Jenkins pull request check | 1 | yes | yes |
   | `test` | Jenkins check, `quantsim/dev-verified` | 0 | no | no |
   | `acceptance` | Jenkins check, `quantsim/test-verified` | 0 | no | no |
   | `main` | Jenkins check, `quantsim/acceptance-signoff` | 1 | no | no |

   "Up to date" and "linear history" stay off on promotion branches: promotion pull
   requests are merge commits, and requiring up-to-date branches would force `develop`
   to merge `test` back after every promotion. Turn protection on after Jenkins has
   reported once, so the check names exist to select.
4. **Cloudflare Pages:** nothing to create by hand; the first ACC deploy creates the
   `quantsim` project. If that name is taken, Cloudflare adds a suffix and the scripts
   read the real address from the API.

## Design decisions

| Decision | Why |
|---|---|
| Images tagged by content, not commit | Promotion merges create new commits; content hashes let every environment reuse the image built and tested on develop |
| Commit statuses gate promotion | A Jenkins approval alone cannot stop someone opening the next pull request; a required status on the exact commit can |
| No "up to date" or linear history on promotion branches | Both would block or force back-merges on every merge-commit promotion |
| Traefik limited to its own compose project | All environments share one Docker host; without the constraint each gateway would route other environments' containers |
| Gateway reads Docker through a read-only socket proxy | The gateway never holds the raw Docker socket |
| Smoke test checks the content hash | A stale container that still answers `/healthz` cannot pass for a new release |
| Approval stages hold no executor | A build waiting overnight does not block everyone else's builds |
| Deploy files are never bind-mounted | Compose runs inside the Jenkins container, whose workspace paths do not exist on the Docker host |
| Secrets decrypted with a pinned SOPS container | Identical on laptops and in Jenkins; the plaintext exists only for the duration of a deploy |

## Known limitations

- Jenkins can use the host's Docker socket, which is equivalent to root on that host, and
  builds run on the controller. Acceptable for one machine; a separate build agent is the
  next step.
- DEV, TEST and Jenkins share one machine and stop when it is off.
- Without a public URL, GitHub webhooks cannot reach Jenkins; it scans the repository
  every 2 minutes instead.
- The frontend was imported from `develop-poc` with a subtree merge. `git log` shows the
  full POC history, but per-file history (`git log -- frontend/src/...`) starts at the
  import.
