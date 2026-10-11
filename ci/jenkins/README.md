# QuantSim Jenkins

Jenkins runs in Docker from this folder. Its plugins, login, roles, credentials,
environment locks, build agent and the `quantsim` job are all defined here, so any
machine becomes the team's CI server with the same few commands, and nothing depends
on clicks in the UI.

| File | Purpose |
|---|---|
| `Dockerfile` | Controller: `jenkins/jenkins:2.580.1-lts` with pinned plugins and configuration as code |
| `agent/` | Build agent image: Jenkins SSH agent with the Docker CLI; every build runs here |
| `plugins.txt` | Pinned plugin versions |
| `casc/jenkins.yaml` | Shared configuration: agent, credentials, locks, global settings, the job |
| `casc/security/local.yaml` | Login for a laptop host: one local `admin` account |
| `casc/security/github.yaml` | Login for the CI server: team members sign in with GitHub |
| `compose.yml` | Controller, agent and an optional public tunnel |
| `compose.server.yml` | CI server additions: Caddy (HTTPS) and GitHub sign-in |
| `Caddyfile` | HTTPS routes for Jenkins, DEV and TEST on the CI server |
| `init-env.sh` | Prepares a host: agent SSH key, `.env`, secret check |
| `bootstrap-server.sh` | Turns a fresh Ubuntu server into the CI server |
| `host.sh`, `lease.sh` | Taking turns hosting: state hand-over through R2 and the host lease |
| `backup.sh` | Nightly backup of Jenkins and the agent's recorded releases |
| `secrets/` | Credential files, never committed (see `secrets/README.md`) |

## How it works

```
anyone pushes ─▶ GitHub ─▶ Jenkins controller (schedules, never builds)
                              │ SSH on the private compose network
                              ▼
                          build agent ── host Docker ──▶ images, DEV and TEST stacks
```

- **One Jenkins at a time.** Whichever machine runs these containers is the team's CI
  server. Two running at once would both build, deploy and post statuses; `host.sh`
  enforces one host through a lease.
- **Pushes from anyone are built.** Jenkins only makes outbound calls to GitHub. It
  scans the repository every 2 minutes on a laptop (5 on the server, where GitHub's
  webhook also starts builds immediately).
- **DEV and TEST run on the host machine,** because the agent deploys through the
  host's Docker.
- **While the host is off or asleep nothing builds.** Builds start once it is back.
  The CI server removes that limitation.

## Take turns hosting on laptops

Any team member can host Jenkins, one at a time, and it stays the same whoever runs it:
the same configuration (from the repository), the same job history and build numbers,
the same recorded releases for rollback, and the same DEV and TEST images.
`host.sh` hands Jenkins' state over through Cloudflare R2 and keeps a **host lease** there
so two laptops never run Jenkins at once.

```bash
ci/jenkins/host.sh status    # who hosts Jenkins now, and its link
ci/jenkins/host.sh start     # take over hosting on this laptop
ci/jenkins/host.sh stop      # hand over: stop Jenkins here and upload its state
```

- `start` refuses while someone else's lease is fresh (seen in the last 10 minutes). If
  their laptop died without `stop`, wait 10 minutes or use `start --force`; anything
  that changed on their machine since its last `stop` is lost.
- `start` fetches the latest state if someone else hosted since, opens a free public
  link (`https://<random>.trycloudflare.com`, shown by `status`), and rebuilds `develop`
  and `test` so DEV and TEST come up on this laptop from the same images.
- Always `stop` before closing the laptop for the day, so the next person gets your
  latest state.
- Everyone signs in with their own account from `secrets/team_users` (below); the
  built-in `admin` account remains as a break-glass login.

### One-time setup per laptop
Needs Docker Desktop with about 10 GB free disk and 4 GB memory for Docker.

1. Get the secret files from a teammate over a private channel and put them in
   `ci/jenkins/secrets/` (see `secrets/README.md`), including the two R2 keys.
2. From the repository root: `ci/jenkins/init-env.sh`
3. In Docker Desktop turn on **Start Docker Desktop when you sign in**.

### Team accounts
Each member gets their own Jenkins login on every laptop host, with their own
permissions. Add one line per person to `secrets/team_users` and share the file with
the other secrets:

```
# github-username:password:role
Ali-Mazhar05:<a long password>:admin
AfnanRizwan1:<a long password>:approver
SaintOfAllOranges:<a long password>:approver
```

| Role | Can |
|---|---|
| `admin` | Everything, including Jenkins settings |
| `approver` | Build, cancel and replay jobs, see logs, and approve ACC and PROD |
| `developer` | Build, cancel and replay jobs and see logs |

`init-env.sh` turns the file into Jenkins accounts (`ci/jenkins/.state/`, never
committed) and makes `approver` and `admin` users the release approvers. After changing
it, run `ci/jenkins/init-env.sh` and restart Jenkins (`host.sh stop`, `host.sh start`).
On the CI server team members sign in with GitHub instead.

### One-time setup for the team (Cloudflare R2, free)
1. Cloudflare dashboard → R2 → create a bucket named `quantsim-ci`.
2. R2 → Manage API tokens → create a token with **Object Read & Write** on that bucket
   only. Save its Access Key ID and Secret Access Key as `secrets/r2_access_key_id` and
   `secrets/r2_secret_access_key`, and share them with the team like the other secrets.

### Hosting alone, without hand-over
`docker compose -f ci/jenkins/compose.yml up -d --build` runs Jenkins on this machine
without R2, the lease or the public link. Use it only when nobody else hosts.

## Host it on the CI server (always on, free)

Oracle Cloud's Always Free tier gives an ARM server permanently at no cost. With it,
Jenkins, DEV and TEST stay up whether or not anyone's laptop is on, and the team reaches
them over HTTPS.

### 1. Create the server (Oracle console)
1. Sign up at cloud.oracle.com. Choose the home region carefully; it cannot be changed.
   Less busy regions have Ampere capacity more often.
2. Compute → Instances → Create instance:
   - Image **Ubuntu 24.04**, shape **VM.Standard.A1.Flex**, **2 OCPU, 12 GB memory**
     (leaves 2 OCPU / 12 GB of the free allowance for a second server later)
   - Boot volume **100 GB**
   - Your SSH public key
   - If it reports "out of capacity", retry later or try another availability domain.
3. Networking → the instance's subnet → Security list → add ingress rules for TCP
   **80** and **443** (and UDP 443) from `0.0.0.0/0`.
4. Always Free instances that stay idle for 7 days can be stopped by Oracle. Upgrading
   the account to Pay As You Go removes that rule while Always Free resources stay
   free; set a budget alert of $1 if you do.

### 2. Give it free names
At duckdns.org (sign in with GitHub) create a subdomain such as `quantsim-ci` pointing
at the server's public IP. `ci.`, `dev.` and `test.quantsim-ci.duckdns.org` then all
reach the server.

### 3. GitHub
- **OAuth App** (Settings → Developer settings → OAuth Apps → New): homepage
  `https://ci.quantsim-ci.duckdns.org`, callback
  `https://ci.quantsim-ci.duckdns.org/securityRealm/finishLogin`. Save its client id
  and a client secret as `secrets/github_oauth_client_id` and
  `secrets/github_oauth_client_secret`.
- **GitHub App** `quantsim-jenkins` → General → Webhook: tick Active, URL
  `https://ci.quantsim-ci.duckdns.org/github-webhook/`. Pushes then build within seconds.
- Add every team member's GitHub username to `casc/security/github.yaml` (developer
  role) through a pull request.

### 4. Set up the server
```bash
ssh ubuntu@<server-ip>
git clone https://github.com/Ali-Mazhar05/QuantSim-FYP.git quantsim   # use a token or deploy key
cd quantsim
sudo ci/jenkins/bootstrap-server.sh
exit                                       # log in again so the docker group applies
scp -r ci/jenkins/secrets/* ubuntu@<server-ip>:quantsim/ci/jenkins/secrets/   # from your laptop
ssh ubuntu@<server-ip>
cd quantsim
ci/jenkins/init-env.sh --server --domain quantsim-ci.duckdns.org \
  --email you@example.com --approvers "Ali-Mazhar05,<teammate>"
docker compose -f ci/jenkins/compose.yml up -d --build
```

Then stop the laptop Jenkins. Jenkins is at `https://ci.quantsim-ci.duckdns.org`,
DEV at `https://dev...` and TEST at `https://test...`. The server builds `linux/arm64`
natively and `linux/amd64` through emulation, so images run on the server and on
laptops.

### Keeping it current
`git pull` on the server, then `docker compose -f ci/jenkins/compose.yml up -d --build`.

## Day to day

| Task | How |
|---|---|
| Logs | `docker compose -f ci/jenkins/compose.yml logs -f jenkins` (or `agent`) |
| Restart after a configuration or secret change | `docker compose -f ci/jenkins/compose.yml up -d --build --force-recreate` |
| Stop (data is kept) | `docker compose -f ci/jenkins/compose.yml down` |
| Add a team member (server) | Their GitHub username under `developer` in `casc/security/github.yaml`, rebuild |
| Allow someone to approve ACC and PROD | Add their user id to `--approvers` and re-run `init-env.sh`, then `up -d` |
| Recorded releases per environment | In the agent: `/home/jenkins/agent/releases/<env>/` |
| Upgrade Jenkins | Change `FROM` in `Dockerfile`, refresh `plugins.txt` (remove versions, rebuild, pin what resolved), rebuild |

## Backup and restore

`backup.sh` archives the `jenkins_home` and `agent_home` volumes (without workspaces,
caches and plugins, which come back by themselves) into `/var/backups/quantsim`,
keeping 14 of each. The CI server runs it nightly; with R2 credentials in
`/etc/quantsim-backup.env` it also copies them off-site. Restore instructions are at
the top of the script.

## Security notes

- The controller runs no builds and has no access to Docker; only the agent does.
- The agent can use the host's Docker, which is equivalent to root on that host. That is
  what lets it build and deploy; keep the host dedicated to CI.
- On the CI server Jenkins listens only on 127.0.0.1; Caddy is the only way in, over
  HTTPS. Only GitHub accounts listed in `casc/security/github.yaml` get any access.
- The controller reaches the agent over SSH with a key that never leaves `secrets/`;
  the agent is not exposed outside the compose network.
