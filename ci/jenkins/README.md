# QuantSim Jenkins

The Jenkins controller runs in Docker from this folder. Its plugins, users, roles,
credentials, environment locks and the `quantsim` multibranch job are all defined here,
so a fresh Jenkins is one command away and nothing depends on clicks in the UI.

| File | Purpose |
|---|---|
| `Dockerfile` | `jenkins/jenkins:2.580.1-lts` plus the Docker CLI (buildx, compose) and jq |
| `plugins.txt` | Pinned plugin versions |
| `casc.yaml` | Configuration as code: security, roles, global settings, credentials, locks, the job |
| `compose.yml` | Runs the controller with a persistent volume and the host's Docker socket |
| `secrets/` | Credential files, never committed (see `secrets/README.md`) |

## First start

1. Fill every file listed in `secrets/README.md`.
2. From the repository root:
   ```bash
   docker compose -f ci/jenkins/compose.yml up -d --build
   ```
3. Open http://localhost:8080 and sign in as `admin`.
4. The `QuantSim` job scans QuantSim-FYP and builds `develop`, `test`, `acceptance`,
   `main`, `feature/*`, `bugfix/*`, `hotfix/*` and pull requests. `develop-poc` and
   `master` are never built.

## Day to day

| Task | Command or place |
|---|---|
| Logs | `docker compose -f ci/jenkins/compose.yml logs -f` |
| Restart after a config or secret change | `docker compose -f ci/jenkins/compose.yml up -d --build --force-recreate` |
| Stop (data is kept) | `docker compose -f ci/jenkins/compose.yml down` |
| Add a team member | Add a user under `securityRealm.local.users` in `casc.yaml` with a password secret, rebuild |
| Allow someone to approve ACC and PROD | Add their user id to `RELEASE_APPROVERS` in `casc.yaml`, rebuild |
| Recorded releases per environment | `/var/jenkins_home/releases/<env>/current.env` and `previous.env` |

## Upgrading

Change the `FROM` line in `Dockerfile`, then update `plugins.txt` (remove the versions
to take the newest compatible ones, rebuild, and pin the versions the build resolved).
Rebuild with `up -d --build`.

## Backup and restore

All state lives in the `quantsim-jenkins_jenkins_home` volume.

```bash
# backup
docker run --rm -v quantsim-jenkins_jenkins_home:/data -v "$PWD":/backup alpine \
  tar czf /backup/jenkins_home.tgz -C /data .
# restore into an empty volume
docker run --rm -v quantsim-jenkins_jenkins_home:/data -v "$PWD":/backup alpine \
  tar xzf /backup/jenkins_home.tgz -C /data
```

## Security notes

- Anonymous users see nothing; every signed-in user can build, only `admin` administers.
- Jenkins can use the host's Docker socket, which is equivalent to root on the host.
  This is accepted for a single-machine setup. The production-grade alternative is a
  separate build agent so the controller never runs builds itself.
- Builds run on the controller's executors for the same reason.
