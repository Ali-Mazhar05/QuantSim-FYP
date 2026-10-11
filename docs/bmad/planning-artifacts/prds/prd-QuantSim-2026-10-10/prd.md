---
title: QuantSim Iteration 1 — Delivery Pipeline and Market Data Ingestion
status: draft
created: 2026-10-10
updated: 2026-10-10
iteration: 1 (Sep–Oct 2026, gate Mid-I)
inputs:
  - docs/proposal/QuantSim_Requirements_Specification.pdf (v0.2, "SPEC")
  - docs/proposal/QuantSim_Architecture_and_Physical_Design.pdf (v0.2, "ARC")
  - FYP_Documentation.pdf (FYP-1 Mid Report draft, "MID")
  - docs/ingestion-plan.md, docs/iteration-plan.md, docs/progress-log.md (branch feature/iteration-plan)
  - docs/ci-cd.md, Jenkinsfile, ci/ (origin/develop and feature/centralized-jenkins)
  - Nasdaq Trader symbol directory (nasdaqlisted.txt, otherlisted.txt)
---

# PRD: QuantSim Iteration 1 — Delivery Pipeline and Market Data Ingestion

## 0. Document Purpose

This PRD covers what QuantSim must deliver by the end of Iteration 1, which the FYP-1 Mid evaluation (Mid-I) assesses. It has three features: the **delivery pipeline** (CI/CD), the **platform foundation** that every service needs (sign-in, roles, audit), and the **market data ingestion engine** (module M1). It is written for the three team members, who build from it, for the supervisors and evaluators, who assess against it, and for the BMAD epics-and-stories and OpenSpec workflows that turn it into tasks.

Conventions:
- **Glossary terms (§3)** are used exactly; no synonyms.
- **Requirement IDs.** FRs are numbered FR-1 to FR-N for this PRD. Each FR cites the SPEC IDs it realizes (for example FR-MKT-011) and the MID IDs (FR-01 to FR-16) where they apply. That way the Mid report, the SPEC and the stories all trace to the same statements.
- **Assumptions** are tagged inline as `[ASSUMPTION: …]` and listed again in §11.
- **The POC is the UI contract.** The frontend imported from `develop-poc` (`frontend/` on `develop`) is the single source of truth for every screen. No requirement in this PRD adds a screen, field, column or control the POC does not have. Backend APIs are shaped to the POC's types, and a capability with no POC screen is API-only (reachable through each service's interactive API docs). Addendum §G maps each POC screen to its API.
- **Technical choices** (vendor, queue design, column types, tooling) live in `addendum.md`, together with the requirement crosswalk and the reconciliation of conflicting sources. This PRD states capabilities and testable consequences.

## 1. Vision

QuantSim is a research environment where a strategy and its portfolio can be run against replayed or simulated markets, then analysed with conventional risk measures, topological data analysis and machine learning, without risking real money. Every later module (simulator, trading engine, risk, TDA, ML, dashboard) consumes market data. Each of them is only as trustworthy as that data and as the process that ships it.

Iteration 1 therefore builds the two foundations everything else stands on.

The first is a **market data ingestion engine** that turns free end-of-day vendor data into clean, auditable price history. It fetches daily bars for a curated list of US-listed instruments and checks every bar against explicit cleaning rules before anyone can use it. It records exactly what it passed, corrected and rejected, and why. Prices are exact decimals. Re-running a window never duplicates anything, and a late vendor correction becomes a visible revision rather than a silent overwrite. Returns and volatility are computed once and published, so no downstream module re-derives them differently.

The second is a **delivery pipeline** that lets three students ship that engine safely. Every change is checked automatically and built once into an image. The same image is promoted unchanged through four environments (DEV, TEST, ACC, PROD), with smoke tests, human approvals, automatic rollback and a tagged release. Any team member can reach the pipeline, and it runs entirely on free services.

At Mid-I the team demonstrates the two foundations together. An admin signs in, adds instruments, triggers an ingestion run and watches deliberately planted bad data get rejected with reasons. Re-running the window adds nothing. Throughout, the pipeline history shows the code reaching TEST through the same gates it will use for the rest of the project.

## 2. Target User

### 2.1 Jobs To Be Done

**Platform users** (the four SPEC §1 roles):
- **Admin** (platform operator): keep a trustworthy list of tracked instruments; get fresh data every trading day without babysitting it; know immediately when a run failed or rejected data; control who can do what.
- **Quant** (builds simulations and portfolios): use price history that is exact, complete for every trading session, and adjusted for splits and dividends when asked; trust that the same query returns the same answer tomorrow unless a recorded revision explains the difference.
- **Analyst** (studies risk): see what was rejected and why, which sessions are missing, and how fresh the data is before relying on it.
- **Viewer** (reads results): read data without being able to change anything.

**Delivery users** (the team, MID §8.3):
- **Developer** (every team member): get a clear pass or fail on every pull request within minutes; never have to remember manual deploy steps; see their change running in DEV after merge.
- **Pipeline approver** (named team members): decide what reaches ACC and PROD, knowing it is exactly what passed TEST; undo a bad release without a scramble.
- **CI host** (whichever member's machine or server runs Jenkins): keep the pipeline available to everyone at no cost, and hand it over without losing history.

**Evaluators** (supervisor and panel, MID §1.8.4): verify each claim from observable evidence (live demo, test reports, pipeline history, commits from every member) rather than from the report alone.

### 2.2 Non-Users (Iteration 1)

- Members of the public and external testers. Access is limited to team accounts.
- Anyone needing intraday, real-time or live-tick data. The source is end-of-day and pseudo-real-time only (SPEC §5).
- Commercial users. Free vendor data is licensed for personal, non-commercial use only.

### 2.3 Key User Journeys

- **UJ-1. Zara runs the Mid demo from a clean environment.**
  - **Persona + context:** Zara is the admin and is running the demo spine for the panel on TEST.
  - **Entry state:** signed out; TEST is running the release that passed DEV.
  - **Path:** Zara signs in on the POC sign-in page. Through the market service's API docs, Zara adds three instruments; for each, the system confirms the symbol against the official exchange listings and fills in the listing exchange. The POC Instruments page now lists them. Zara triggers an ingestion run and gets an acknowledgement at once. When the run finishes, Zara opens the POC Audit Log page.
  - **Climax:** the Audit Log shows a Market Data event for the run: "Ingestion run completed", severity Warning, with a detail line counting what was received, passed untouched, corrected and rejected, and naming the rules that rejected the planted defects. The full Reconciliation report, read through the API docs, adds up exactly. The POC Market Data page draws the clean bars.
  - **Resolution:** Zara triggers the same window again; the new Audit Log event reports zero new bars, and no new Events are published. A viewer account then tries to add an instrument and is refused.
  - **Edge case:** the vendor is unreachable during the demo. The run ends `partially_succeeded` with deferred instruments named, and the catch-up run picks them up later. The planted-fault demo uses recorded vendor responses, so the demo itself never depends on the vendor (FR-24).

- **UJ-2. Bilal pulls ten years of adjusted history for a backtest.**
  - **Persona + context:** Bilal is a quant preparing an Iteration 2 simulation calibration.
  - **Entry state:** signed in as a quant.
  - **Path:** Bilal requests daily bars for an instrument from 2015-01-02 to today, then requests the return series for the same window.
  - **Climax:** Bilal receives one clean bar per trading session (no weekends or holidays), exact decimal prices, a split-adjusted series, and log returns with 20- and 60-session volatility.
  - **Resolution:** Bilal stores the request parameters. The same request next week returns the same values unless a recorded revision explains the difference.
  - **Edge case:** the vendor corrected one session last night. Bilal sees `revision: 2` on that bar, and the previous values are retained.

- **UJ-3. Hina checks data quality before a stress test.**
  - **Persona + context:** Hina is an analyst about to run correlation-based analysis in a later iteration.
  - **Entry state:** signed in as an analyst.
  - **Path:** Through the market API, Hina reads the data-quality summary, sorts by open gaps, then reads the rejected bars for the latest run. (No POC screen shows these; they are API-only.)
  - **Climax:** Hina sees each instrument's last clean session, its bar count, its open gaps and its flagged bars, plus every rejected record with the rules it broke and the raw payload.
  - **Resolution:** Hina excludes one instrument with an unresolved gap from the analysis basket.

- **UJ-4. Omar ships a fix from branch to DEV.**
  - **Persona + context:** Omar is a developer fixing a cleaning-rule bug.
  - **Entry state:** a feature branch with a one-line commit.
  - **Path:** Omar runs the local preflight, pushes and opens a pull request into `develop`. Jenkins posts a check within minutes covering lint, types, tests and the migration check. A teammate reviews and Omar merges.
  - **Climax:** within minutes of the merge, DEV runs the new image and the smoke test confirms the deployed content hash. The commit shows `quantsim/dev-verified`.
  - **Resolution:** Omar opens the promotion pull request `develop → test`, which can merge because the DEV status is green.
  - **Edge case:** a migration has no working downgrade. The pull request check fails at the migration check before review starts.

- **UJ-5. Ali releases v0.1.0 and recovers from a bad deploy.**
  - **Persona + context:** Ali is an approver.
  - **Entry state:** TEST is verified.
  - **Path:** Ali merges `test → acceptance`. The ACC deploy reuses the TEST image without rebuilding it. Ali checks ACC and gives acceptance sign-off. Ali merges `acceptance → main` and approves production.
  - **Climax:** PROD serves the same content hash, and the commit is tagged `v0.1.0`.
  - **Resolution:** the release is recorded and can be rolled back.
  - **Edge case:** a later ACC smoke test fails. The pipeline rolls ACC back to the previous release automatically and reports the failure. No sign-off is possible until a fix passes.

- **UJ-6. Afnan takes over hosting Jenkins for the week.**
  - **Persona + context:** Afnan is a team member taking a turn as CI host because the shared server is unavailable.
  - **Entry state:** the previous host stopped Jenkins cleanly.
  - **Path:** Afnan checks the hosting status, then starts Jenkins locally. The hand-over restores the full Jenkins state, opens a public address and redeploys DEV and TEST.
  - **Climax:** teammates open the new address, sign in and see the full build history.
  - **Edge case:** the previous host is still running. Afnan's start is refused until the other host stops or its lease expires.

- **UJ-7. The overnight run meets a vendor outage.**
  - **Persona + context:** the scheduled daily run at 22:30 UTC, with no human involved.
  - **Path:** after 5 consecutive vendor failures, the run stops calling the vendor and defers the remaining instruments. It ends `partially_succeeded`.
  - **Climax:** the 06:00 UTC catch-up run ingests the deferred instruments without duplicating the ones that already succeeded.
  - **Resolution:** Zara sees both runs in the run history the next morning, each with its reasons.

## 3. Glossary

*Market data*
- **Instrument** — A tradable security tracked by QuantSim: an exchange-listed equity or ETF in Iteration 1. It is identified by symbol plus listing exchange, and its status is `active` or `retired`.
- **Instrument master** — The admin-maintained set of all Instruments, including retired ones.
- **Symbol directory** — The official daily lists of US-listed securities published by Nasdaq Trader (`nasdaqlisted.txt` for Nasdaq listings, `otherlisted.txt` for NYSE, NYSE American, NYSE Arca, Cboe BZX and IEX listings). Used to validate Instruments; never used as a price source.
- **Vendor** — An external free source of end-of-day prices (Tiingo in Iteration 1; see addendum).
- **Session** — One trading day of an Instrument's exchange, per its Trading calendar.
- **Trading calendar** — The open sessions, holidays, early closes and close times of an exchange.
- **Bar** — The OHLCV record (open, high, low, close, volume) of one Instrument for one Session. It also carries the session close timestamp in UTC, a Revision number, Quality flags, and the dividend and split values for that Session.
- **Ingestion run** — One execution of the ingestion engine over a window of Sessions for a set of Instruments. Its mode is `daily`, `catchup`, `manual` or `backfill`, and its status is `pending`, `running`, `succeeded`, `partially_succeeded` or `failed`.
- **Run item** — The outcome of one Ingestion run for one Instrument.
- **Cleaning gate** — The set of Cleaning rules every vendor record must pass before it is published as a Bar.
- **Cleaning rule** — A named check with a severity: `reject` (the record is not published), `correct` (published after a recorded fix), or `flag` (published with a Quality flag).
- **Rejected bar** — A vendor record the Cleaning gate refused. It is retained with every rule it broke and its raw payload.
- **Quality flag** — A label on a published Bar, for example `zero_volume` or `outlier`.
- **Data gap** — An expected Session with no clean Bar. It resolves automatically when the Bar arrives.
- **Revision** — A changed vendor value for an already-published Bar. The Bar's revision number increases and the previous values are retained.
- **Reconciliation report** — The per-run and per-Instrument accounting of records received, passed untouched, corrected, duplicates removed and rejected, with counts per Cleaning rule, Quality flags and Data gaps.
- **Ruleset version** — The identifier of the Cleaning gate rules applied, stored on each Ingestion run.
- **Return series** — Per-Instrument, per-Session log return, split/dividend-adjusted log return, and 20- and 60-session annualised volatility.
- **Corporate action** — A split or cash dividend recorded for an Instrument on a Session.
- **Market environment** — A named market a simulation or portfolio runs inside, exactly as the POC models it: type `Historical Replay` or `Synthetic Market`, a universe name, a set of Instruments, a start and end date, a frequency (`Daily`, `Hourly`, `Tick`) and a status (`Draft`, `Ready`, `Active`). Iteration 1 creates, lists and validates Market environments; replay playback and synthetic generation are Iteration 2.
- **Market environment interface** — The published contract (tick event schema plus operations) shared by replayed and simulated markets, so a portfolio can bind to either.
- **Event** — A fact published to the event backbone after its change is committed, for example `bar.ingested`, `bar.corrected`, `instrument.created`, `instrument.retired` or `user.deactivated`.
- **Planted-fault dataset** — A fixed set of vendor records with known defects, plus the exact Reconciliation report the Cleaning gate must produce for it.
- **Vendor budget** — The shared hourly allowance of Vendor requests, set below the Vendor's free limits.

*Platform*
- **User** — A person with a QuantSim account and exactly one Role. A User is `active` or `deactivated`.
- **Role** — One of `admin`, `quant`, `analyst`, `viewer` (SPEC §1).
- **Access token** — A short-lived signed token proving a User's identity and Role, verifiable by any service without calling the issuer.
- **Audit entry** — The before- and after-state of one insert, update or delete on business data, with the acting User and request id.

*Delivery*
- **Environment** — One of four deployments: **DEV** (from `develop`), **TEST** (from `test`), **ACC** (from `acceptance`, with sign-off) and **PROD** (from `main`, with approval).
- **Component** — A separately built and deployed unit: the frontend, or a backend service such as `platform` or `market`.
- **Content hash** — A short hash of the source files a Component is built from. It is the Component's image identity.
- **Image** — The built container for one Component at one Content hash. It is built once and never rebuilt for promotion.
- **Promotion** — Moving an already-built Image to the next Environment through a pull request between environment branches.
- **Commit status** — A pass/fail mark Jenkins posts on a commit: `continuous-integration/jenkins/branch`, `quantsim/dev-verified`, `quantsim/test-verified` or `quantsim/acceptance-signoff`.
- **Smoke test** — A post-deploy check that each Component is healthy and serves the expected Content hash.
- **Rollback** — Redeploying the previously recorded release of an Environment.
- **Release** — A PROD deploy tagged `v<VERSION>` (Iteration 1: `v0.1.0`).
- **Pipeline approver** — A team member's Jenkins account allowed to give acceptance sign-off and production approval. This is not a QuantSim User.
- **CI host** — The machine currently running Jenkins: the shared server, or one team member's laptop.
- **Host lease** — A record that a CI host is active, refreshed every 2 minutes. It prevents two CI hosts running at once.

## 4. Features

### 4.1 Delivery Pipeline (CI/CD)

**Description:** One Jenkins pipeline serves every Component.
- **Pull requests:** every pull request is checked automatically.
- **`develop` branch:** every Component whose Content hash is new is built into an Image, deployed to DEV and smoke tested.
- **Promotion:** each Promotion pull request (`develop → test → acceptance → main`) deploys the *same* Images to the next Environment.
- **Gates:** ACC requires acceptance sign-off and PROD requires approval by a Pipeline approver. A successful PROD deploy is tagged as a Release.
- **Failure handling:** failures on ACC or PROD roll back automatically.

The branch `develop-poc` stays frozen as the POC reference and is never built. `master` stays empty. Everything uses free services only. Realizes UJ-4, UJ-5 and UJ-6.

The pipeline itself has been working for the frontend since 2026-10-07: DEV and TEST are verified, and ACC failed its first run because of a Pages certificate wait (fix in PR #12). Iteration 1 still has to:
- extend the pipeline to the backend Components,
- make it reachable by the whole team (centralized Jenkins), and
- complete the first ACC and PROD Release.

**Functional Requirements:**

#### FR-1: Pull request checks
A Developer gets an automated pass/fail on every pull request into `develop` and on every feature, bugfix and hotfix branch. The check covers pipeline-script linting, frontend lint, type check, tests with coverage and build, and, for each backend Component, lint, format, type check, tests and the migration check. Realizes UJ-4. *(SPEC NFR-MNT-004, NFR-REC-001; MID §6.2 item 6, TC evidence)*

**Consequences (testable):**
- Jenkins posts `continuous-integration/jenkins/branch` on the pull request head commit for every pull request.
- A pull request containing a migration whose downgrade fails gets a failed check.
- Test results (JUnit) and frontend coverage are published on the Jenkins build page.
- With the CI host online and idle, the check result is posted within 15 minutes of the push. `[ASSUMPTION: 15 min target; measured 2 min 13 s for the frontend-only pipeline]`

#### FR-2: Build once, deploy DEV automatically
Merging into `develop` builds an Image only for each Component whose Content hash has no Image yet, deploys DEV and runs the Smoke test. On success it posts `quantsim/dev-verified` on the commit. Realizes UJ-4. *(SPEC NFR-MNT-001, NFR-MNT-004)*

**Consequences (testable):**
- A merge that changes only the market service builds only the `market` Image; other Components keep their existing Images and are not rebuilt.
- The DEV Smoke test fails if any Component serves a Content hash different from the one deployed.
- `quantsim/dev-verified` is posted only after a successful DEV Smoke test.

#### FR-3: Promotion without rebuild
Merging a Promotion pull request deploys to TEST, ACC or PROD the exact Images that were verified in the previous Environment. Realizes UJ-5. *(SPEC NFR-MNT-001)*

**Consequences (testable):**
- The pipeline refuses to deploy (error "Not built on develop") if any required Image is missing, and never builds during Promotion.
- The Content hash served in TEST, ACC and PROD equals the one verified in DEV for the same source.
- A successful TEST deploy posts `quantsim/test-verified`.

#### FR-4: Promotion gates
A Promotion pull request may merge only when the previous Environment's Commit status is green: `quantsim/dev-verified` for `test`, `quantsim/test-verified` for `acceptance`, and `quantsim/acceptance-signoff` for `main`. Realizes UJ-4 and UJ-5.

**Consequences (testable):**
- Each Commit status appears on the Promotion pull request head commit.
- The rule is written in `docs/ci-cd.md` and enforced by the git-flow skill's `pr.sh promote`. That script refuses to open a Promotion pull request whose head lacks the required status. `[ASSUMPTION: GitHub branch protection is unavailable on the free private plan, so team convention plus tooling enforce the gate]`

#### FR-5: Acceptance sign-off and production approval
After a successful ACC deploy, a Pipeline approver must accept or reject the release within 24 hours; the result is posted as `quantsim/acceptance-signoff`. On `main`, a Pipeline approver must approve production within 24 hours before PROD is deployed. Only Pipeline approvers can respond. Realizes UJ-5.

**Consequences (testable):**
- A non-Pipeline approver cannot submit either decision.
- A rejection or a timeout posts `quantsim/acceptance-signoff` as failure, and the build ends ABORTED.
- Waiting for a decision holds no build executor.

#### FR-6: Automatic rollback on ACC and PROD
If the deploy or the Smoke test fails on ACC or PROD, the pipeline redeploys that Environment's previously recorded release and smoke tests it. Realizes UJ-5.

**Consequences (testable):**
- A deliberately broken release on ACC ends with ACC serving the previous Content hash, and the build is marked failed.
- An Pipeline approver can trigger a manual Rollback to the previous release of any Environment.

#### FR-7: Release tagging
A successful PROD deploy tags every Image and the git commit with `v<VERSION>` from the `VERSION` file. Realizes UJ-5.

**Consequences (testable):**
- The pipeline fails before deploying if `v<VERSION>` already exists.
- At the end of Iteration 1, tag `v0.1.0` exists on `main`, and PROD serves the Content hashes that tag records.

#### FR-8: Environment isolation
DEV and TEST can run on the same host without affecting each other, and each Environment deploys only its own Components. *(SPEC NFR-MNT-002)*

**Consequences (testable):**
- Redeploying DEV leaves TEST's containers, data and routes untouched.
- Each Environment's gateway routes only to its own Components.

#### FR-9: Encrypted per-Environment secrets
Each Environment's secrets (database passwords, signing keys, the Vendor API key) are stored encrypted in the repository. Only the pipeline decrypts them, at deploy time. *(SPEC NFR-SEC-003; MID §4.5.4)*

**Consequences (testable):**
- No plaintext secret exists in the repository, in any Image or in build logs.
- A team member can be granted decryption by adding their public key and re-encrypting, without changing any secret value.
- The pipeline deletes the decrypted file when the deploy step ends, whether the deploy passed or failed.

#### FR-10: Team access to a centralized Jenkins
Every team member can reach Jenkins at one stable HTTPS address and sign in with their GitHub account, which maps to the Developer or Pipeline approver role. Anonymous visitors are refused. Realizes UJ-4 and UJ-5.

**Consequences (testable):**
- An anonymous request to Jenkins gets HTTP 403 or a login redirect.
- A GitHub account outside the configured team list cannot sign in.
- GitHub push events trigger builds through a webhook; without a webhook, Jenkins scans for changes every 5 minutes or less.
- `[ASSUMPTION: shared server is the Oracle Cloud Always Free VM (Toronto) with a free DuckDNS name; until it is provisioned, FR-11 is the operating mode]`

#### FR-11: Turn-taking Jenkins host
Any team member can become the CI host on their laptop. Jenkins state (configuration, jobs, build history, release records) is handed over through free cloud storage, and a Host lease prevents two hosts at once. Realizes UJ-6.

**Consequences (testable):**
- Starting a host restores the previous host's build history.
- A start is refused while another host's lease is fresh, meaning refreshed less than 10 minutes ago.
- `[ASSUMPTION: Cloudflare R2's free tier may require a card on file; no charges are incurred within its free allowance]`
- After a start, DEV and TEST are redeployed on the new host and teammates can reach them at the new public address.

#### FR-12: Jenkins backup
The shared CI host backs up Jenkins state nightly and keeps the last 14 backups. *(SPEC NFR-REC-002 is Extended; this is the minimal Iteration 1 form)*

**Consequences (testable):**
- A restore from the latest backup into a fresh Jenkins brings back jobs, credentials references and build history.

#### FR-13: Backend Components join the pipeline
A backend service joins the pipeline when one Component entry is added. From then on it gets FR-1 to FR-9, including running database migrations before the new version starts and stopping the deploy if a migration fails. *(SPEC NFR-MNT-004, NFR-REC-001; migration protocol in addendum §B)*

**Consequences (testable):**
- `platform` and `market` each pass the pull request checks, deploy to DEV and TEST, and pass a Smoke test on `/api/<service>/health` that reports the deployed Content hash.
- A deploy whose migration fails leaves the previous version running and marks the build failed.

**Feature-specific NFRs:**
- **Free:** every service used has a free tier with no card-required paid usage. `[ASSUMPTION: Oracle Always Free may require a card on file; no charges are incurred]`
- **Reproducible:** the CI host is defined as code: Jenkins configuration as code, pinned plugins, a pinned Jenkins LTS version and a bootstrap script. A new host can be built from the repository plus secrets alone. Test: a fresh host built from the bootstrap script, configuration as code and a backup restore runs a green pipeline with no manual Jenkins configuration.
- **Least privilege:** the Jenkins controller has no Docker access; builds run on a separate agent.

**Notes:**
- ACC and PROD serve only the frontend (Cloudflare Pages) until a backend server exists. `[ASSUMPTION: the Mid demo of backend behaviour runs on TEST; backend on ACC/PROD follows once the Oracle server is up]`
- `[NOTE FOR PM]` The Mid report draft (§6.5, Table 5) says "CI pipeline — Completed — GitHub Testing". The pipeline is Jenkins, not GitHub Actions, and the evidence is the Jenkins build history plus the Commit statuses. Correct this before submission.

### 4.2 Platform Foundation (Identity, Roles, Audit)

**Description:** The Platform service (M0) owns Users, Roles and sign-in. It issues Access tokens that every other service verifies locally, so a Platform outage stops sign-in but not the rest of the system. Every service records Audit entries for its own business data and publishes Events through a transactional outbox. This feature exists in Iteration 1 because the ingestion engine needs authenticated, role-checked, audited access (MID §3.4 "Authentication and protected API access"). Realizes UJ-1 (sign-in, viewer refused).

**Functional Requirements:**

#### FR-14: User accounts and Roles
An admin can create a User with a unique username, email and Role, and can deactivate, reactivate and change the Role of a User. History is preserved; nothing is deleted. *(SPEC FR-PLT-001, -002, -003; NFR-INT-002, NFR-SEC-004)*

**Consequences (testable):**
- The database refuses a Role outside {admin, quant, analyst, viewer}.
- Passwords are stored only as salted one-way hashes. A password has at least 12 characters and never appears in logs or Audit entries.
- The last active admin cannot be deactivated or demoted, including under concurrent requests.
- Deactivation and Role changes publish `user.deactivated`, `user.reactivated` and `user.role_changed` Events.
- On a fresh Environment, the first admin is created from that Environment's encrypted secrets during deploy. Running the deploy again creates no second admin. No admin password exists in plaintext in the repository or the working tree.
- Quant, analyst and viewer Users get HTTP 403 on every user-management operation and on audit history reads.

#### FR-15: Sign-in and token verification
A User signs in with username and password and receives an Access token valid for 15 minutes. Every service verifies Access tokens locally against the Platform's published public keys, without calling the Platform per request. *(SPEC FR-PLT-004; NFR-SEC-001)*

**Consequences (testable):**
- Expired, forged and wrongly signed tokens are rejected with HTTP 401.
- A wrong password, an unknown user and a deactivated account all get the same response.
- After 5 failed attempts, sign-in is refused for 15 minutes (HTTP 429).
- When the Platform is stopped, already-issued tokens still work on other services until they expire. *(SPEC NFR-REL-006)*
- Sign-in also returns a refresh token. Exchanging it for a new Access token rotates it: the old refresh token stops working, and presenting an already-used refresh token revokes every refresh token of that session (theft detection). Refresh tokens are stored server-side, only as hashes, and expire after 12 hours.
- Sign-out revokes the session's refresh token; the POC Sign out button calls it. Deactivating a User or changing their Role revokes all of their refresh tokens.
- The role the POC sign-in page and top-bar switcher show can preview only the account's own Role or a lower one (viewer < analyst < quant < admin). The backend always authorizes with the account's real Role, so a preview never grants anything.

**Out of Scope:**
- Sign-in with GitHub or Google (OAuth2 social login). Decided 2026-10-12: deferred to a later iteration once a fixed domain exists, because the POC sign-in page has no such button and OAuth callbacks need stable addresses. Our tokens already follow the OAuth2/OIDC building blocks (signed JWT, JWKS), so adding it later only adds an identity exchange in the Platform service.

#### FR-16: Role checks on every route
Every endpoint of every service declares the Roles allowed to call it and refuses all others. The service that owns the data makes the decision. *(SPEC FR-PLT-005; NFR-SEC-001; MID TC-05, TC-06)*

**Consequences (testable):**
- A request with no token gets HTTP 401. A valid token with a disallowed Role gets HTTP 403.
- An automated test enumerates every route and fails if any route lacks a Role declaration.
- A role-by-route matrix test calls every route with each of the four Roles and checks the expected HTTP 2xx or 403 against the Roles each FR states.

#### FR-17: Revocation
Deactivating a User or changing their Role makes that User's previously issued Access tokens stop working on every service. *(SPEC FR-PLT-002, FR-PLT-003)*

**Consequences (testable):**
- After deactivation, a token issued before it is refused by the market service within 5 seconds. `[ASSUMPTION: 5 s bound; shared revocation list]`
- If the revocation store is unreachable, services refuse tokens (fail closed).

#### FR-18: Audit trail
Every insert, update and delete on audited business data (Users, Instruments) records an Audit entry with the before-state, the after-state, the acting User and the request id. Audit entries cannot be changed or deleted, and they remain queryable after the audited row is deleted. *(SPEC FR-PLT-006, -007, -008; NFR-AUD-001, -002; NFR-INT-005)*

**Consequences (testable):**
- An insert, an update and a delete each produce exactly one Audit entry.
- An UPDATE, DELETE or TRUNCATE on the audit table fails, even when run by the table owner.
- The ordered change history of one User or Instrument can be read through the API (admin only).
- Columns designated secret (password hashes) are excluded from Audit entries.

#### FR-19: Reliable Events
A state change and the Events it produces are committed together. A broker outage delays Event delivery but never loses an Event or blocks the write, and consuming the same Event twice has no additional effect. *(SPEC NFR-REL-007, NFR-REL-008; NFR-OBS-003)*

**Consequences (testable):**
- With the broker stopped, writes succeed and their Events are delivered after the broker returns.
- Replaying an already-processed Event to a consumer changes nothing.
- The number of unpublished Events (outbox backlog) is exposed as a metric.

### 4.3 Market Data Ingestion Engine (M1)

**Description:** Admins maintain the Instrument master, validated against the Symbol directory. On a schedule, and on demand, the engine fetches end-of-day Bars from the Vendor within the Vendor budget. Every record passes through the Cleaning gate. The engine then publishes clean Bars, records Rejected bars, Data gaps, Revisions and Corporate actions, computes the Return series, and publishes Events. Each Ingestion run produces a Reconciliation report. Signed-in users read Bars, returns, run history and data quality through the market API. Realizes UJ-1, UJ-2, UJ-3 and UJ-7.

**Functional Requirements:**

#### FR-20: Instrument master
An admin can add an Instrument (symbol, name, sector, listing exchange, currency, asset class `equity` or `etf`, optional Vendor symbol, notes), annotate its name, sector and notes, and retire it. Adding, annotating and retiring are API-only; the POC Instruments page is read-only. Retiring is non-destructive and repeating it has no further effect. All signed-in Users can list Instruments, filtered by status. Realizes UJ-1. *(SPEC FR-MKT-001; FR-PLT-006)*

**Consequences (testable):**
- Adding an Instrument whose symbol and exchange already exist returns HTTP 409, even if the existing Instrument is retired. The response names the existing Instrument id and status. Re-activating a retired Instrument is out of scope for Iteration 1.
- A retired Instrument keeps its Bars and history, appears in history queries, and is excluded from every later Ingestion run.
- Adding and retiring publish `instrument.created` and `instrument.retired` Events and produce Audit entries.
- Quant, analyst and viewer Users get HTTP 403 on add, annotate and retire.
- A seed command loads the starting universe of 40 Instruments (30 large-cap equities, 10 ETFs). Running it again adds nothing. `[ASSUMPTION: D5 universe accepted]`

#### FR-21: Instrument validation against the Symbol directory
When an admin adds an Instrument, the system checks the symbol against the latest Symbol directory and fills in or confirms the listing exchange. The directory is refreshed daily, and the system reports active Instruments that have left it. Realizes UJ-1. *(New in this PRD: strengthens FR-MKT-001 with official reference data)*

**Consequences (testable):**
- A symbol listed in the Symbol directory is accepted. Its exchange is set from the directory's exchange code: Nasdaq → XNAS, NYSE → XNYS, NYSE American → XASE, NYSE Arca → ARCX, Cboe BZX → BATS, IEX → IEXG.
- A symbol marked as a test issue in the Symbol directory is refused (HTTP 422, reason `test_issue`).
- A symbol not found in the Symbol directory is refused (HTTP 422, reason `not_listed`). An admin can add it anyway by supplying an explicit override reason, which is recorded in the Audit entry.
- The asset class `etf` is suggested when the directory marks the security as an ETF.
- After each daily refresh, active Instruments missing from the Symbol directory are listed in the data-quality view as `delisted_candidate`. They are never retired automatically.
- If an admin supplies an exchange that differs from the directory's, the add is refused (HTTP 422, reason `exchange_mismatch`) unless an override reason is supplied.
- If the directory download fails, the last successful copy is used. A copy older than 3 days is still used, but the response carries a `stale_directory` warning and the data-quality view shows it. Each failed refresh is logged, and the directory's age is a metric.
- On a fresh Environment with no copy at all (download failed and none stored), the add is refused (HTTP 503, reason `directory_unavailable`) unless an override reason is supplied. The seed command (FR-20) does not depend on the directory.
- Validation never blocks for longer than 5 seconds; on timeout the system behaves as for a failed download.
- `[ASSUMPTION: the Symbol directory is used under Nasdaq's terms for non-commercial reference; confirm before any public deployment]`

#### FR-22: Scheduled and on-demand Ingestion runs
The engine creates a `daily` Ingestion run at 22:30 UTC and a `catchup` run at 06:00 UTC on every calendar day. Admins can trigger a `manual` run (optional window and Instrument list) or a `backfill` run (explicit start date; default 2015-01-02). Each run covers every active Instrument unless restricted. Realizes UJ-1 and UJ-7. *(SPEC FR-MKT-002; NFR-PERF-004; MID FR-01)*

**Consequences (testable):**
- A trigger request returns HTTP 202 with the run id within 800 ms, and the work proceeds asynchronously.
- If the schedule fires twice, for example from two scheduler instances, only one `daily` run is created per date.
- The default window starts 5 Sessions before each Instrument's last stored Bar and ends at the latest Session whose close has passed. "Today" is the exchange's local date (America/New_York for XNYS). A new Instrument starts at the backfill start date.
- A run whose window contains no new Sessions (for example on a weekend) ends `succeeded` with zero new Bars.
- A `daily` run starts within 15 minutes of 22:30 UTC even when a backfill is in progress. `[ASSUMPTION: 15 min bound replaces "backfill never delays the daily run"]`
- Backfill and manual runs cannot spend the part of the Vendor budget reserved for that day's `daily` and `catchup` runs: one request per active Instrument per run.
- Triggering a run whose Instruments and window overlap an unfinished run returns HTTP 409 with the id of the active run.
- Quant, analyst and viewer Users get HTTP 403 when triggering a run.
- The scheduler is enabled in exactly one Environment per Vendor API key (TEST in Iteration 1). Other Environments create runs only when an admin triggers them.
- Each run records its mode, status, window, requesting User (or `scheduler`), Ruleset version, start and finish times, and error, plus one Run item per Instrument with counts and error.

#### FR-23: Idempotent ingestion with Revisions
Ingesting the same window again adds no Bars and publishes no Events. A vendor value that changed for an already-published Bar creates a Revision: the Bar's revision number increases, the previous values are retained, and a `bar.corrected` Event is published. Realizes UJ-1 and UJ-2. *(SPEC FR-MKT-002; NFR-REL-005, NFR-REL-008)*

**Consequences (testable):**
- Running an identical window twice results in zero new Bars, zero Revisions and zero Events on the second run.
- Changing one vendor close value and re-running produces exactly one Revision and one `bar.corrected` Event, and the previous value can be read.
- A run interrupted mid-way, then re-run, leaves the same final Bars, Revisions and Events as an uninterrupted run.
- When two workers are running, a run is executed by only one of them at a time.
- A vendor correction that fails the Cleaning gate creates no Revision. The published Bar stays as it was, and the corrected record is stored as a Rejected bar.

#### FR-24: Resilient Vendor access
Every Vendor call is bounded by a timeout and counted against the Vendor budget shared by all workers. Transient failures are retried with backoff. Repeated failure stops further calls for the rest of the run, so that a Vendor outage degrades a run instead of hanging it. Realizes UJ-7. *(SPEC NFR-PERF-005, NFR-REL-006; MID §7.6 "External data source unavailable", "Malformed provider response")*

**Consequences (testable):**
- Each Vendor call times out after at most 30 seconds.
- Timeouts, HTTP 5xx responses and HTTP 429 are retried, up to 4 attempts in total. A `Retry-After` header is honoured. Unknown symbols and refused requests are not retried.
- After 5 consecutive Vendor failures, the remaining Instruments in the run are deferred and the run ends `partially_succeeded`, naming the deferred Instruments. Only timeouts, HTTP 5xx and HTTP 429 count toward the 5; unknown symbols do not.
- A Vendor authentication failure (HTTP 401 or 403) ends the whole run at once as `failed`, with reason `vendor_auth`, and makes no further Vendor calls.
- An Instrument deferred by 2 consecutive runs is shown in the data-quality view with its deferral count.
- One Vendor budget is shared by every Environment and worker that uses the same Vendor API key, and combined usage never exceeds the configured hourly budget.
- When the Vendor budget is exhausted, remaining Instruments are deferred rather than the run waiting for the next hour.
- An unknown symbol fails only its own Run item, with a reason, and the other Instruments continue.
- A malformed Vendor response fails its Run item with reason `malformed_response`. Nothing from that response is published.
- No automated test calls the real Vendor. All tests use recorded responses.
- An Environment can be switched to a fixture Vendor that serves recorded responses, for example for the Planted-fault dataset on TEST. Fixture data is ingested only for dedicated planted Instruments, marked as such, and excluded from SM-4 and from the data-quality totals of real Instruments.

#### FR-25: Cleaning gate
Every vendor record passes the Cleaning gate before it can become a Bar. Each record is checked against every Cleaning rule. Realizes UJ-1 and UJ-3. *(SPEC FR-MKT-011; MID FR-02, TC-02, TC-03)*

| Cleaning rule | Severity | Applies when |
|---|---|---|
| `malformed` | reject | a field is missing or unparsable |
| `outside_window` | reject | the date was not requested |
| `non_trading_day` | reject | the date is a weekend or exchange holiday |
| `non_positive_price` | reject | any price ≤ 0 |
| `ohlc_order` | reject | low > high, or open/close outside [low, high] |
| `negative_volume` | reject | volume < 0 |
| `duplicate_conflict` | reject | the same Session appears twice with different values (all copies rejected) |
| `duplicate_removed` | correct | the same Session appears twice with identical values (one copy kept) |
| `zero_volume` | flag | volume = 0 |
| `outlier` | flag (configurable to reject) | the absolute log return from the previous close exceeds 0.405 (≈50%), except on a split day |

**Consequences (testable):**
- No published Bar ever has a price ≤ 0 or high < low (property test over generated inputs), and the database refuses such a row even if it bypasses the gate.
- Every published Bar's timestamp is its Session's actual close in UTC from the Trading calendar, which handles daylight-saving changes and early closes.
- A Rejected bar is stored with every rule it broke and its raw payload. It is never silently dropped.
- An expected Session with no clean Bar is recorded as a Data gap only once its close plus 12 hours has passed, so the 06:00 UTC catch-up run is the first to judge it. This avoids false gaps from late Vendor publication. Holidays are never recorded as gaps. A Data gap resolves when its Bar arrives.
- The Ruleset version (Iteration 1: `2026.10.1`) is stored on each run.

#### FR-26: Reconciliation report
Each Ingestion run produces a Reconciliation report for the run as a whole and for each Instrument. Realizes UJ-1 and UJ-3. *(SPEC FR-MKT-011, FR-MKT-002)*

**Consequences (testable):**
- For every Instrument and for the run total, the report satisfies **received = passed untouched + corrected + duplicates removed + rejected** (property test).
- The report lists counts per Cleaning rule, Quality flags, new and resolved Data gaps, new Bars and Revisions.
- Running the Planted-fault dataset produces a report identical to the stored expected report, field for field.

#### FR-27: Returns and volatility
After each run, the engine recomputes the Return series for each affected Instrument, starting at the earliest new or revised Session. It stores the results and publishes them in the `bar.ingested` Event. Realizes UJ-2. *(SPEC FR-MKT-003)*

**Consequences (testable):**
- Definitions:
  - **log return:** ln(closeₜ / closeₜ₋₁) over consecutive Sessions.
  - **adjusted log return:** the same calculation on the Vendor's split- and dividend-adjusted close.
  - **N-session volatility:** the sample standard deviation (n − 1) of the last N adjusted log returns × √252. It is undefined until N returns exist.
- The values match a hand-computed fixture to within 1 × 10⁻⁸ absolute.
- A split day shows no jump in the adjusted log return, and a dividend day's adjusted log return equals the value computed by hand from the adjusted closes.
- A Revision on an old Session triggers recomputation from that Session onward and nowhere else.

#### FR-28: Corporate actions and adjusted prices
The engine records splits and cash dividends from Vendor data and keeps both raw and adjusted price series. *(SPEC FR-MKT-010, Extended, included because the Vendor supplies it at no extra cost)*

**Consequences (testable):**
- A split in the Vendor data creates one Corporate action with a split factor > 0. Requesting Bars with `adjusted=true` returns prices adjusted for it.
- A cash dividend in the Vendor data creates one Corporate action with the cash amount on its ex-date Session.
- Raw Bars are never overwritten by adjusted values.

#### FR-29: Market read API
Signed-in Users can read Instruments, Bars (raw or adjusted, by Instrument and date range, paginated) and the Return series. Admins, quants and analysts can also read the run history, run detail with its Reconciliation report, Rejected bars with reasons, and the data-quality summary (last Session, Bar count, open Data gaps and flagged Bars for each Instrument). Realizes UJ-2 and UJ-3. *(SPEC FR-MKT-001..003, FR-MKT-011; MID FR-03, TC-04)*

**Consequences (testable):**
- The Instrument list returns exactly what the POC Instruments page shows for each Instrument: symbol, name, sector, the latest clean close as price, and the change percentage from the previous clean close. An Instrument with fewer than two clean Bars returns no price or change, and the page shows it without them.
- Bars for an Instrument and window are returned in Session order, with exact decimal prices, revision numbers and Quality flags. The POC Market Data page draws the last 90 sessions from this.
- Each finished Ingestion run adds one event to the platform audit feed that the POC Audit Log page reads: user (the requesting User, or `System` for scheduled runs), service `Market Data`, action `Ingestion run completed`, `Ingestion run partially succeeded` or `Ingestion run failed`, severity `Info` (nothing rejected), `Warning` (rejections, gaps or deferrals) or `Critical` (failed), and a one-line detail with the counts and the rejecting rules.
- Run history, run detail, Rejected bars and the data-quality summary are API-only; no POC screen shows them.
- Each Bar carries its provenance: the Ingestion run that published its current revision, the Vendor, and the Ruleset version. Previous revisions carry the same fields.
- A viewer gets HTTP 403 on run history, Rejected bars and data quality.
- The API contract is exported as an OpenAPI document on every build, and the frontend's typed client is generated from it.
- Standard reads complete within 800 ms at p95 for a 1-year window of one Instrument: 200 sequential requests from one client, measured through the gateway on TEST. *(SPEC NFR-PERF-002)*

#### FR-30: Market environments and the market environment interface
Admins and quants can create a Market environment with the fields the POC Create Market Environment page collects (name, type, universe, 1–100 existing Instruments, start date, end date, frequency); it starts as `Draft`. All signed-in Users can list and read Market environments with the fields the POC Market Environments page shows (name, type, universe, window, frequency, status). Analyst and viewer Users get HTTP 403 on create. The tick Event schema of the Market environment interface is published in the repository. Replay playback (play, pause, speed and session position, as on the POC Replay page) and synthetic generation are out of scope (Iteration 2). *(SPEC FR-MKT-007 create, FR-MKT-008, FR-MKT-009; NFR-INT-003)*

**Consequences (testable):**
- A Market environment whose end date is not after its start date is refused by the API (HTTP 422) and also by the database when inserted directly.
- A type, frequency or status outside the POC's values is refused by the API (HTTP 422) and by the database.
- The tick Event schema exists under `contracts/events/` with a schema version, and an automated test validates sample Events against it.
- Coverage of FR-MKT-009 in Iteration 1 is partial: only the schema is delivered. The operations that bind a portfolio to a market come in Iteration 2 with the simulator.

#### FR-31: Market data observability
Every run, Vendor call and outbox drain emits structured logs and metrics, so that operators can see failures and staleness without reading code. *(SPEC NFR-OBS-002, NFR-OBS-003)*

**Consequences (testable):**
- Every log line from ingestion carries the run id, the Instrument and the Vendor, and never contains the Vendor API key.
- Metrics exist for:
  - runs by status and run duration
  - Bars by outcome and rejections by rule
  - Vendor calls by status and latency
  - Vendor budget waits and circuit state
  - outbox backlog
- `/api/market/health` reports the build Content hash. `/api/market/ready` returns 503 while the database or Redis is unreachable.

**Feature-specific NFRs:**
- Prices and money are stored and computed as fixed-precision decimals with 8 decimal places, never binary floating point, from Vendor response to API output. *(SPEC NFR-INT-001)*
- The market database is built from its own migration history alone, and every migration is reversible. *(SPEC NFR-REC-001; migration protocol in addendum §B)*
- The market service owns `market_db` exclusively; no other service reads it directly. *(SPEC NFR-MNT-002, NFR-SEC-007)*

**Notes:**
- `[NON-GOAL for Iteration 1]`
  - Rolling correlation series (SPEC FR-MKT-004) is a stretch goal, built only if the critical path is done. Otherwise it moves to Iteration 3 with TDA.
  - News ingestion (FR-MKT-006) is Iteration 2.
  - Replay playback (FR-MKT-007 play, pause, speed) is Iteration 2.

## 5. Cross-Cutting NFRs

| ID | Requirement (SPEC) | Iteration 1 target and evidence |
|---|---|---|
| NFR-PERF-002 | Standard API operations within 800 ms at p95 | Measured on TEST through the gateway for market reads and platform user operations; result recorded in the Mid report |
| NFR-PERF-003 | Audit triggers add ≤20% write latency | Measured once on `instrument` inserts; result recorded |
| NFR-PERF-004 | Job submission acknowledged within 800 ms | FR-22 |
| NFR-PERF-005 | Every synchronous dependency call has a timeout | FR-24, plus JWKS fetch timeouts |
| NFR-REL-005/007/008 | Idempotent, reclaimable jobs; atomic commit-and-publish; idempotent consumers | FR-19, FR-23 |
| NFR-REL-006 | Declared degraded behaviour per dependency | Platform down → tokens still verify; Vendor down → deferral; broker down → outbox backlog |
| NFR-INT-001/002/003/005 | Decimals; Role constraint; replay window check; append-only audit | FR-14, FR-18, FR-25, FR-30 |
| NFR-SEC-001/003/004/007 | Authorization in owning service; no secrets in source or Images; hashed passwords; per-service DB credentials | FR-9, FR-14, FR-16; one database role per service |
| NFR-AUD-001/002 | Audit coverage and history reconstruction | FR-18 |
| NFR-OBS-002/003 | Structured logs and metrics; outbox backlog | FR-19, FR-31 |
| NFR-REC-001 | Schema from migrations only | FR-13, migration check on every pull request |
| NFR-MNT-001/002/004/006 | Same Image everywhere; DB per service; per-Component pipeline; shared template | FR-2, FR-3, FR-13 |
| NFR-MNT-005 | Additive API evolution, checked by contract tests | Iteration 1 partial: OpenAPI exported per build and the frontend type check breaks on incompatible changes |

**Deferred Core NFRs.** These are Core in the SPEC but not delivered in Iteration 1. They are also listed in §8.2, and Open Question 8 confirms their targets:
- **NFR-OBS-001 (end-to-end tracing):** stretch in Iteration 1, otherwise Iteration 2. `[ASSUMPTION]`
- **NFR-SEC-002 (TLS on every internal hop):** Iteration 1 has TLS only at the public edge (CI host and Pages); internal hops follow in Iteration 4 with the production orchestration. `[ASSUMPTION]`
- **NFR-AUD-003 (audit-index Events):** Iteration 2, when a second service with audited data needs cross-service investigation. `[ASSUMPTION]`

## 6. Constraints and Guardrails

- **Cost:** free tiers and open-source software only, with no paid services (team decision; MID §1.10).
- **Data licence:** Vendor and Symbol directory data are used for non-commercial research only and are not redistributed in bulk. A public deployment needs licence confirmation (MID §1.11).
- **Scope of use:** QuantSim executes no real transactions and gives no investment advice (MID §1.6.3).
- **Process:**
  - Work flows `feature/*` → `develop` → `test` → `acceptance` → `main` through pull requests, one branch per task.
  - Commit messages are one line with no punctuation and no AI attribution.
  - `develop-poc` is never modified or deleted; `master` stays empty.
- **Schema changes:** follow the migration protocol (addendum §B).
- **Hardware:** team laptops have limited disk. Heavy builds and the full stack run on the CI host. `[ASSUMPTION: 20 GB free kept on any laptop acting as CI host]`
- **AI disclosure:** AI-assisted work is disclosed in the Mid report (MID §8.7, Form 3).

## 7. Non-Goals (Explicit)

- QuantSim does not provide intraday, real-time or live-tick data, and does not use a paid data feed.
- QuantSim is not a public multi-tenant service in Iteration 1: there is no self-registration and no external users.
- Iteration 1 includes no Kubernetes, service mesh, read replicas, point-in-time recovery or high-availability broker. These SPEC Extended items are planned for Iteration 4.
- Iteration 1 does not run a second Vendor or cross-check outliers between vendors.
- Market data does not include asset classes other than US-listed equities and ETFs (MID §1.6.3).
- Iteration 1 includes no simulation, trading, risk, ML, TDA or alerting features.
- No screen, field, column or control is added to the POC UI. Wiring POC pages to the real APIs (sign-in, Instruments, Market Data, Market Environments, Users, Audit Log, System health) replaces mock data only; layout and content stay as the POC defines them.

## 8. Iteration 1 Scope

### 8.1 In Scope, by priority

All FRs below are planned for Iteration 1. If time runs short, cut from the bottom tier upward, in the order listed. Never cut a Must. Tiers accepted by the team on 2026-10-10.

| Tier | FRs | Why |
|---|---|---|
| **Must** (the Mid demo and its failure cases) | FR-1, FR-2, FR-3, FR-8, FR-9, FR-13, FR-14, FR-15, FR-16, FR-18, FR-19, FR-20, FR-22 (manual and daily runs), FR-23, FR-24, FR-25, FR-26, FR-27, FR-29, FR-30 | Without these there is no demo spine, no planted-fault evidence and no failure cases |
| **Should** | FR-4, FR-5, FR-6, FR-7 (the `v0.1.0` Release), FR-11, FR-17, FR-31 (logs plus health and ready at minimum) | Release evidence and safe operation |
| **Could**, cut in this order | 1. FR-21 Symbol directory (fall back to a reviewed static seed list) · 2. FR-28 corporate actions (keep the Vendor-adjusted close for FR-27) · 3. SM-8 full backfill (backfill 2 years) and the FR-22 catch-up run · 4. FR-31 full metrics list · 5. FR-12 backup and the FR-10 webhook (FR-11 rotation suffices) · 6. backend on ACC and PROD | Valuable, but the demo does not depend on them |

### 8.2 Out of Scope for Iteration 1
- Rolling correlation series (FR-MKT-004). Stretch; otherwise Iteration 3.
- News ingestion (FR-MKT-006). Iteration 2.
- Replay playback and tick streaming (FR-MKT-007 play, pause, speed). Iteration 2.
- Versioned baskets (FR-MKT-005). Extended.
- End-to-end tracing (NFR-OBS-001). Stretch; first to cut.
- TLS on internal hops (NFR-SEC-002) and audit-index Events (NFR-AUD-003). See §5.
- Sign-in with GitHub or Google (FR-15 Out of Scope).
- Backend on ACC and PROD, if no server exists by the Release. Frontend-only ACC and PROD are acceptable for `v0.1.0`.
- `[NOTE FOR PM]` Correlation is the first piece of analytical evidence the TDA work needs. Revisit if the critical path finishes early.

## 9. Success Metrics

**Primary**
- **SM-1: The demo spine passes on TEST.** The UJ-1 sequence runs end to end on TEST from a fresh deploy: sign in, add instruments, trigger a run, see the run on the Audit Log page and the bars on the Market Data page, re-run with zero additions, viewer refused, inverted Market environment window refused. Target: passes twice in a row at the rehearsal (I1-52). Validates FR-14 to FR-16, FR-20 to FR-26, FR-29 and FR-30.
- **SM-2: The Planted-fault report matches exactly.** The run report equals the expected report field for field on DEV and TEST. Target: 100% match. Validates FR-25 and FR-26.
- **SM-3: The first Release is complete.** `v0.1.0` is tagged on `main`. For every Component that ACC and PROD host (at least the frontend), they serve the Content hash TEST verified. `quantsim/acceptance-signoff` was posted by a Pipeline approver. Target: by Mid-I. Validates FR-3 to FR-7.
- **SM-4: Daily ingestion is reliable.** Over the last 5 trading days before Mid-I, the scheduled `daily` runs on TEST end `succeeded` for all 40 real Instruments on at least 4 days, and no day is missing a run. Requires an always-on CI host for those days: the Oracle server, or a named team member's machine left on. If neither exists, SM-4 is replaced by a log of manual runs on those days. Validates FR-22 to FR-24.

**Secondary**
- **SM-5: Pipeline feedback time.** The median pull request check time is ≤10 minutes. FR-1's 15 minutes is the ceiling for any single check; this is the typical target. Validates FR-1.
- **SM-6: Every member contributes.** Each of the three members authors at least 3 merged pull requests in Iteration 1 and demos their own task. Validates the MID rubric criteria 6 and 8. `[NOTE FOR PM]` On 2026-10-10, every Iteration 1 commit is authored by one member. This is the largest rubric risk; see Open Question 10.
- **SM-7: Requirement coverage.** Every FR in §4 has at least one automated test or one recorded demo step that references it. Validates the MID §4.7 traceability.
- **SM-8: Full backfill within budget.** The 2015-01-02 backfill of 40 Instruments completes within one day without exceeding the Vendor budget. Validates FR-22 and FR-24.

**Counter-metrics (do not optimize)**
- **SM-C1: Rejection rate.** Do not tune Cleaning rules to make the rejection rate small. A rule that rejects real defects is working. Counterbalances SM-4.
- **SM-C2: Test count and coverage percentage.** Do not chase numbers. A test that does not check an FR consequence does not count toward SM-7. Counterbalances SM-7.
- **SM-C3: Deploy frequency.** Do not skip approvals or push to environment branches to ship faster. Counterbalances SM-3 and SM-5.
- **SM-C4: Ingestion speed.** Never raise the Vendor budget above the Vendor's free limits to finish faster. Counterbalances SM-8.

## 10. Open Questions

1. **Mid-I date:** resolved 2026-10-10. The team owns the schedule; SM targets marked "by Mid-I" are relative to whatever date the team sets.
2. **Price precision:** resolved 2026-10-10. Stored prices use 8 decimal places (`NUMERIC(23,8)`, as in ARC §8.9); volume `NUMERIC(28,8)`. Applies from the first market schema migration.
3. **Tiingo free limits:** 50 requests per hour, 1,000 per day and 500 symbols per month are third-party reports. Confirm on tiingo.com before relying on SM-8.
4. **Feature pull request merge method:** `docs/ci-cd.md` says squash and the git-flow skill says rebase. Pick one.
5. **Vercel integration:** a Vercel app posts statuses on the repository but is not part of the design. Keep or disconnect?
6. **Oracle server timing:** if the server is not up before the Release, ACC and PROD stay frontend-only (§8.2). Confirm this is acceptable to the supervisor.
7. **API version segment:** ARC §7.1 requires `/v1/` in URLs; the current routes are `/api/<service>/…`. Decide before the frontend client is generated (I1-41).
8. **Deferred Core NFRs** (NFR-OBS-001, NFR-SEC-002, NFR-AUD-003): confirm the target iteration for each.
9. **Mid report alignment:** the MID draft uses its own FR-01 to FR-16 and says performance targets will be "defined using measured results" (§4.5.3), while the SPEC sets 800 ms and 2 s. Decide which numbering and targets the report presents. The crosswalk is in addendum §A.
10. **Contribution evidence:** all Iteration 1 work so far is committed by one member. Task owners will be assigned by the team later; SM-6 needs merged pull requests from every member.
11. **Tiingo key sharing:** does the free personal licence allow one key to be used by a team server? If not, each Environment that ingests needs its own key, and the shared budget (FR-24) applies per key.
12. **Sensitive files in the working tree:** an untracked `admin_password` file and `ci/jenkins/.state/` must be git-ignored before anyone runs `git add .` (FR-9).
13. **POC Users page status `Invited`:** resolved 2026-10-12. Derived with no schema change: `Active` = has signed in at least once, `Invited` = created but never signed in, `Disabled` = deactivated.
14. **Audit feed for the POC Audit Log page:** the POC shows readable events (time, user, service, action, severity, detail), while each service's audit log stores row-level before and after values. The platform needs a readable activity feed, fed by events from every service, that the Audit Log page reads. FR-29 defines the market service's events for it; the feed itself is a platform task.
15. **POC sign-in role picker and top-bar role switcher:** resolved 2026-10-12. Both controls stay as in the POC and preview only the account's Role or a lower one; the backend always enforces the real Role (FR-15).

## 11. Assumptions Index

- §4.1 FR-1: the pull request check target is 15 minutes.
- §4.1 FR-4: the promotion gate is enforced by convention and tooling, not GitHub branch protection.
- §4.1 FR-10: the shared CI host is Oracle Always Free with a DuckDNS name; turn-taking laptops are the interim mode.
- §4.1 NFRs: Oracle may require a card on file, but no charges are incurred.
- §4.1 Notes: backend behaviour is demonstrated on TEST until a backend server exists.
- §4.2 FR-17: the revocation bound is 5 seconds, using a shared revocation list.
- §4.3 FR-20: the 40-Instrument universe (30 equities, 10 ETFs) is accepted (D5).
- §4.3 FR-21: the Symbol directory may be used for non-commercial reference.
- §4.3 FR-22: a daily run starts within 15 minutes of its schedule during a backfill.
- §4.1 FR-11: Cloudflare R2's free tier may require a card on file; no charges are incurred.
- §4.2 FR-15: OAuth2 social sign-in is deferred; refresh tokens and sign-out are in scope (decided 2026-10-12).
- §5: target iterations for the deferred Core NFRs (OBS-001: Iteration 2; SEC-002: Iteration 4; AUD-003: Iteration 2).
- §6: any laptop acting as CI host keeps 20 GB free.
