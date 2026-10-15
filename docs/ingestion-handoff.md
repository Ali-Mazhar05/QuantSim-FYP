# Market data ingestion module: handoff

Written 2026-10-14 by Afnan Rizwan for whoever continues this work. It is meant to be read top to bottom once, then used as a reference.
It is a snapshot: where it disagrees with the code or with a merged pull request, the
code wins, and please fix this file.

Related documents: `docs/ingestion-plan.md` (the plan, decisions D1 to D18, risks),
`docs/iteration-plan.md`, `docs/progress-log.md`, `docs/ci-cd-team-guide.md`,
`services/market/README.md` (the service's own runbook and API notes).

---

## 1. Where things stand

**Backend: about 90% of the plan is built and tested. Nothing of the new work is merged
into `develop` yet; it is waiting for review and a green Jenkins. The frontend for the
module is not started.**

| Plan step | What | State |
|---|---|---|
| 1 | Schema, migration `0001`, models | on `develop` |
| 2 | Trading calendar, cleaning gate, returns | on `develop` |
| 2b | ERD generator and diagram | on `develop` (the rendered SVG/PNG is stale, see 11) |
| 3 | Instrument master, routes, 40 instrument seed | PR #59 |
| 4 | Tiingo adapter, request budget, fixture source | PR #57 |
| 5 | Pipeline: run queue, worker, runner, relay | PR #58 |
| 6 | Run routes, scheduler, read API | PR #61, PR #62 (replay sessions and tick schema not built) |
| 7 | Deployment wiring | PR #63 (never run through Jenkins) |
| 8 | Planted-fault demo | partly: tests exist; the fixed dataset, exact-report test and demo script do not |
| 9 | Correlation matrices | PR #65 (no cache table) |
| 10 | Corporate actions | built inside the pipeline and read API |
| 11 | Nasdaq symbol directory | PR #64 |
| n/a | End to end real data tests | PR #60 |

Evidence it works, from this build:
- the whole suite passed on the combined branch (341 tests at that point; the symbol
  directory and correlation branches added their own passing tests afterwards)
- about 17,000 real bars (6 symbols, about 11 years each) go through the gate, the pipeline and
  the read API and are compared with independent numpy and pandas calculations
- a live run against Tiingo with the real key: AAPL, NVDA and KO from 2024-06-03 to
  2024-07-12 gave 84 bars, all equal to the recorded corpus, the NVDA 10 for 1 split of
  2024-06-10 and the dividends stored once each; a second run added nothing

**What blocks "done":** Jenkins has not completed a build of the new pull requests (see 9),
the `MARKET_DB_PASSWORD` secret does not exist, the planted-fault demo and the frontend pages
are missing, and nothing has been deployed to DEV.

---

## 2. Where the code is

### 2.1 Branches and pull requests

All are against `develop`, all open, **none merged**. They are built on each other, so a
later diff also shows earlier commits until the earlier one merges. Merge in this order and
press **Update branch** on the next one after each merge (that shrinks its diff and re-runs
Jenkins).

| Order | PR | Branch | Needs |
|---|---|---|---|
| 1 | #57 | `feature/market-tiingo-adapter` | nothing |
| 2 | #58 | `feature/market-pipeline` | #57 |
| 3 | #59 | `feature/market-instruments` | #57 |
| 4 | #61 | `feature/market-run-api` | #58, #59 |
| 5 | #62 | `feature/market-read-api` | #58, #59 |
| 6 | #63 | `feature/market-deploy` | #61 |
| 7 | #64 | `feature/market-symbol-directory` | #59 |
| 8 | #65 | `feature/market-correlation` | #62 |
| 9 | #60 | `feature/market-ingestion-e2e` | all above; tests only, review its last commits |

Also open: #56 (PRD epics and stories, docs only, Jenkins green). Old PRs #14 and #15
target branches that are already merged and should be closed (they were left open on
purpose, ask before closing).

Notes on the history you will see:
- `feature/market-ingestion-e2e` and `feature/market-run-api`, `-read-api`, `-deploy`
  contain merge commits of sibling branches. They were made to carry Jenkins type-check
  fixes up the stack. That is untidy; once #57 is merged, update each branch from `develop`
  and the noise disappears. Do not rebase pushed branches without telling the others.
- Everything that is on `develop` already: schema (#14/#55), cleaning gate (#18), ERD (#31),
  the plan (#53), the encrypted Tiingo key (#54).

### 2.2 Code map (`services/market`)

```
src/qs_market/
  main.py                  app factory; mounts all routers; builds the symbol directory
  settings.py              all QS_* settings (see 5)
  models.py                SQLAlchemy Core tables, the single source of truth for the schema
  calendars.py             exchange calendars (XNYS etc.), sessions, closes
  cleaning.py              the gate: pure functions, Decimal arithmetic, ruleset 2026.10.1
  returns.py               log returns and 20/60 day volatility
  instruments.py           instrument master service (add, annotate, retire, list, quote)
  api.py                   instrument routes (+ symbol directory check on add)
  api_runs.py              run trigger and run history routes
  api_data.py              bars, returns, corporate actions, gaps, quote, data quality
  api_correlation.py       POST /correlations
  correlation.py           pure correlation maths and fingerprint
  symbol_directory.py      Nasdaq file parser and validator
  seed.py, data/universe.py   the 40 instrument starting universe
  cli.py, __main__.py      worker | relay | scheduler | run-once
  vendor/                  base (interface, errors), tiingo, budget (Redis), fixture, factory
  pipeline/                runs (queue, lock, claim), window, runner (one tx per instrument),
                           scheduler
migrations/versions/       0001 schema, 0002 ingestion_run_item.report
scripts/                   fetch_realdata.py, vendor_check.py, fetch_symbol_directory.py,
                           erd.py, gate_demo.py
tests/                     unit, database (marker db), realdata/ (marker realdata)
```

Shared library: `libs/qs_template` (config, auth with RS256/JWKS and capabilities, outbox
and `add_event`, audit trail with `set_audit_context`, Kafka publisher, revocation list).
The market service does not duplicate any of it.

---

## 3. How it works

### 3.1 Flow

```
POST /ingestion-runs (admin)  or  scheduler (daily 22:30 UTC, catch-up 09:30 UTC, TEST only)
        |  create_run: idempotency key, conflict check, audited transaction
        v
   ingestion_run (pending)  --- worker (advisory lock, SKIP LOCKED claim, recovers orphans)
        |
        |  for each instrument, one database transaction:
        |    1. window  (default: 5 sessions before the last bar -> latest closed session)
        |    2. fetch   (Tiingo adapter: retries, backoff, 45/h budget in Redis)
        |    3. stage   (raw rows kept exactly as received)
        |    4. gate    (accept / flag / reject / dedupe; gaps)
        |    5. publish (new bars; revision + bar.corrected if a raw value changed)
        |    6. record  (rejected_bar, data_gap, corporate_action)
        |    7. returns (return_series recomputed)
        |    8. outbox  (bar.ingested, bar.corrected)
        v
   report on the run item and run; status succeeded | partially_succeeded | failed
        |
   relay: outbox -> Redpanda topic quantsim.market.instrument (event_type distinguishes)
```

### 3.2 Behaviour rules (review code against these)

| Situation | Result |
|---|---|
| Unknown symbol (Tiingo 404) | that instrument fails; the run continues |
| Tiingo refuses the key (401/403) | run `failed` with `vendor_auth`; does not count toward the circuit |
| 5 consecutive transient failures | circuit opens, the rest are deferred, `partially_succeeded` |
| Budget exhausted or Redis down | rest deferred, `partially_succeeded` (fails closed) |
| Every instrument failed | `failed` |
| Worker killed mid run | next worker resumes; instruments already `succeeded`/`no_data` are skipped; final state equals an uninterrupted run |
| Same window again | zero new bars, revisions, events or rejected rows |
| Tiingo restates only adjusted prices | stored, not a correction (no `bar.corrected`) |
| Tiingo changes a raw price of a stored session | new `bar_revision`, one `bar.corrected` per instrument |
| Two runs for the same window and overlapping instruments | 409 naming the active run |
| Scheduler slot while a same window run is active | not marked handled, retried every 30 s |

### 3.3 Cleaning gate (read `cleaning.py` docstrings for the full text)

Pure functions over Decimal; ruleset version `2026.10.1` is stored with every bar. Rejects
(rule names as stored): `non_positive_price`, `ohlc_order`, `negative_volume`,
`non_trading_day` (a date that is not a session of the instrument's calendar) and
`duplicate_conflict` (both copies rejected). Flags (stored, marked): `outlier` (log return
above the threshold, default 0.405, skipped on split days) and `zero_volume`; under the
`reject` outlier policy an outlier is rejected instead of flagged. Identical duplicates are
collapsed. Missing
sessions become gaps (resolved when the bar arrives; grace until close + 12 h so "today" is
not a gap before the vendor publishes). The content hash covers only **raw vendor values**
(open, high, low, close, volume, split factor, dividend), so a restated adjusted price never
looks like a correction.

Precision: raw prices `NUMERIC(23,8)`, volume `NUMERIC(28,8)`, adjusted prices
`NUMERIC(23,10)`, returns and volatility `NUMERIC(20,12)`. Returns are quantised to 12
decimals half even in Python before storing so stored equals computed.

---

## 4. Data model (`market_db`, migration `0001` and `0002`)

`instrument`, `ingestion_run`, `ingestion_run_item` (has the JSON `report` column from
`0002`), `staging_bar`, `bar` (Timescale hypertable), `bar_revision`, `rejected_bar`
(rules + raw payload; one row per distinct rejection), `data_gap`, `corporate_action`
(`split_factor`, `dividend`), `return_series`, `market_environment` (the replay window
table, decision D17; **no API yet**), plus the template tables `outbox`, processed events
and the append only `audit_log`.

Things that bit us:
- `bar` is a hypertable: `TRUNCATE instrument CASCADE` does **not** clear it. The shared test
  fixture now truncates every market table; keep it that way.
- Only `instrument` has the audit trigger. Run, item and bar tables are themselves the
  record of what a run did. Reviewers were asked to confirm that is enough.
- The Timescale extension is created by `db-init` (superuser) in deployed environments and
  by the test fixture; the migration does not create it.
- The generated ERD in `docs/diagrams/market_db.*` is kept in step by a test (the Mermaid
  source). The rendered SVG/PNG is stale; re-render when someone has the tool.

---

## 5. API and configuration

### 5.1 Routes (all under `/api/market`, bodies and errors are problem details)

| Route | Roles | PR |
|---|---|---|
| `GET /instruments?status=`, `GET /instruments/{id}` | any signed in | #59 |
| `POST /instruments`, `PATCH /instruments/{id}`, `POST /instruments/{id}/retire` | admin | #59 (+ directory check #64) |
| `POST /ingestion-runs` (202; `mode` manual or backfill; `instrument_ids` or `symbols`; `idempotency_key`) | admin (needs `trigger_ingestion` and `backfill_market_data`) | #61 |
| `GET /ingestion-runs`, `/{id}`, `/{id}/rejected` | admin, quant, analyst | #61 |
| `GET /instruments/{id}/bars`, `/returns` (keyset paging, `limit` max 2000) | any signed in | #62 |
| `GET /instruments/{id}/corporate-actions`, `/gaps`, `/quote` | any signed in | #62 |
| `GET /data-quality` | admin, quant, analyst | #62 |
| `POST /correlations` | any signed in | #65 |
| `GET /health`, `GET /ready` | anyone | template |

Not built: `POST /replay-sessions`, `GET /replay-sessions/{id}`.
Decimals are always strings. Capability checks are on the backend; the frontend
`permissions.ts` is only a convenience. A test (`test_every_route_has_a_declared_rule`)
fails when a route is added without being listed in the route and role matrix in
`tests/test_instruments_api.py`; add new routes there.

### 5.2 Settings (`QS_*`, see `settings.py`)

| Setting | Default | Meaning |
|---|---|---|
| `QS_DATABASE_URL`, `QS_REDIS_URL`, `QS_KAFKA_BOOTSTRAP_SERVERS`, `QS_AUTH_JWKS_URL` | none | infrastructure |
| `QS_VENDOR` | `fixture` | `tiingo` or `fixture`; `tiingo` refuses to start without a key |
| `QS_TIINGO_API_KEY` | none | secret; never logged |
| `QS_TIINGO_REQUESTS_PER_HOUR` / `QS_TIINGO_SCHEDULED_RESERVE` | 45 / 40 | shared budget; backfill and manual runs may only use the difference (5 per hour) |
| `QS_FIXTURE_DIR` | none | folder of recorded responses |
| `QS_INGEST_BACKFILL_START` | 2015-01-02 | where a new instrument's history starts |
| `QS_INGEST_OUTLIER_LOG_RETURN` / `QS_INGEST_OUTLIER_POLICY` | 0.405 / `flag` | `flag` or `reject` |
| `QS_INGEST_CIRCUIT_FAILURES` | 5 | consecutive transient failures |
| `QS_INGEST_POLL_SECONDS` | 5 | worker poll |
| `QS_INGEST_SCHEDULER_ENABLED`, `QS_INGEST_DAILY_TIME`, `QS_INGEST_CATCHUP_TIME` | false, 22:30, 09:30 UTC | scheduler (TEST only) |
| `QS_SYMBOL_DIRECTORY_DIR`, `QS_SYMBOL_DIRECTORY_MAX_AGE_DAYS` | unset (off), 14 | symbol directory validation |

Secrets live in `deploy/secrets/*.enc.env` (SOPS + age). `TIINGO_API_KEY` is already in all
four. **`MARKET_DB_PASSWORD` is new and missing**; add it with
`ci/scripts/set-secret.sh MARKET_DB_PASSWORD all`. Compose uses `:?`, so deploy and
`db-init` fail loudly until it exists.

---

## 6. Tiingo facts (measured, not assumed)

- One free key, reported by third parties as 50 requests per hour, 1,000 per day and 500
  unique symbols per month (not confirmed on Tiingo's own site; confirm before go-live),
  shared by every environment. No rate limit headers, so the budget is counted by us in
  Redis (key hashed).
- camelCase fields; dates are midnight UTC; raw prices are unadjusted; adjusted values are
  restated at every dividend and split; unknown symbol is 404; latency 1 to 11 s.
- Free tier data is for personal use: the real corpus is git ignored and recorded on demand.
- `scripts/vendor_check.py` checks the real vendor with one symbol (a human runs it).

---

## 7. Testing

| Layer | Where | Needs |
|---|---|---|
| Unit (gate, returns, calendar, adapter, budget, scheduler, correlation maths) | `tests/` | nothing |
| Database | `tests/` marker `db` | `TEST_DATABASE_URL` to a TimescaleDB with the extension |
| Real data | `tests/realdata/` marker `realdata` | recorded corpus; skips when absent |
| Real data end to end | `tests/realdata/test_pipeline_on_real_data.py` and the run and read API ones | corpus + database |

Record the corpus (6 requests): `TIINGO_API_KEY=... uv run python scripts/fetch_realdata.py`
(writes `tests/realdata/corpus`, git ignored; override with `QS_REALDATA_DIR`).

**Run exactly what Jenkins runs**, from `services/market`:

```
uv run ruff check .
uv run ruff format --check .
uv run mypy .          # the whole tree including tests; not just src
uv run pytest
```

The first thing that failed Jenkins was `mypy .` over test files while we only ran
`mypy src`. `ci/scripts/python-ci.sh market` runs the same in the pinned containers.

Test rules we settled on: expected values come from an independent source (numpy, pandas,
the calendar library, the recorded vendor values), a test must not rely on data left by
another test, and nothing in the unit suite may reach the real vendor (a socket guard in
`tests/conftest.py` enforces it).

---

## 8. Local development notes

- Python 3.12 and `uv`; the monorepo is one uv workspace (`uv.lock` at the root, `--frozen`).
- Database for tests (Docker, WSL on this team):
  `docker run -d --name qs-test-db -e POSTGRES_USER=qs -e POSTGRES_PASSWORD=qs -e POSTGRES_DB=qs -p 55433:5432 timescale/timescaledb:2.22.1-pg17`, then
  `TEST_DATABASE_URL=postgresql+asyncpg://qs:qs@127.0.0.1:55433/qs`. Add
  `--restart unless-stopped`; the Docker daemon restarts under us (see 9).
- Run the stack by hand: `alembic upgrade head`, `python -m qs_market.seed`,
  `QS_VENDOR=fixture QS_FIXTURE_DIR=tests/fixtures python -m qs_market run-once --mode backfill --start 2024-01-02 --end 2024-02-13 --symbol AAPL` (expect 30 received, 30 new bars; run it again for 0).
- Windows: `loop.add_signal_handler` is not available; the CLI already tolerates it. Use `;`
  as the `PYTHONPATH` separator in Git Bash.
- Disk: keep the uv cache and temp on a drive with space.
- Branches, commits and PRs follow the repo's `quantsim-git-flow` skill: one line commit
  messages without trailing punctuation, merge commits only, never push to `develop`.

---

## 9. CI and the infrastructure problem

Jenkins is hosted by Ali on a laptop (WSL, Docker, quick tunnel addresses that change on
every restart). For this module:

- PR #56 is green. **#57 to #65 have no real result**: their builds were repeatedly killed
  ("cannot be built", "build was aborted") while the Docker daemon and the WSL distribution
  restarted.
- Probable cause: **disk space**. WSL's disk files are on `D:` (`D:\WSL\Ubuntu\ext4.vhdx`
  about 24 GB, `D:\WSL\docker\ext4.vhdx` about 6.5 GB) and `D:` had under 2 GB free; `C:` had
  about 0.4 GB. When the disk files cannot grow, Docker and Jenkins fall over. One helper
  also ran `wsl --shutdown`, which killed builds in progress. **Nobody should run
  `wsl --shutdown` or `wsl --terminate` while builds are running.**
- Fix: free 15 to 20 GB on `D:` and a few GB on `C:`, optionally compact the two disk files
  (stop Jenkins, `wsl --shutdown`, `Optimize-VHD`; admin rights; `ci/jenkins/compact-docker-disk.ps1`
  was written for Docker Desktop, adapt the paths), then in Jenkins **Scan Repository Now**
  on `quantsim`, or **Build Now** on `PR-57` first.
- Jenkins requires a login, so the failing stage's console text has to be copied by a person.
- The "Vercel" check on every PR fails with "Git author ... must have access to the project
  on Vercel". It is unrelated (the frontend deploys to Cloudflare Pages); ignore it or ask
  Ali to disconnect the Vercel app.
- The CI container user can collide with the shared `qs-ci-cache` volume's owner; if
  `python-ci.sh` says `Failed to initialize cache at /ci-cache/uv: Permission denied`, run it
  with `CI_CACHE_VOLUME=<your own volume name>` after `prepare_ci_cache`.

What we expect from the first green build: lint, format and type checks (verified locally
on every branch), then pytest with a throwaway TimescaleDB (the real data tests skip there),
then image build, deploy to DEV and the smoke test (never exercised yet).

---

## 10. What is left, and how to do it

Ordered by importance for the Mid demonstration. Each item says where and what "done" is.

### 10.1 Must do

1. **Planted-fault dataset, exact-report test and demo script** (plan step 8; "never cut").
   - Where: `tests/fixtures/planted/` (a small fixed vendor response with known defects),
     `tests/test_planted_faults.py`, `scripts/demo_planted_faults.py`, README section.
     `tests/realdata/test_faults_in_real_data.py` already has the fault recipes
     (`AT` indices and `EXPECTED` map) and `scripts/gate_demo.py` shows the gate on a
     sample; reuse both.
   - Approach: choose one symbol and a window of about 40 sessions; plant the eight faults
     (negative price, low above high, weekend date, identical and conflicting duplicate,
     60% jump, zero volume, a missing session); run the real runner on a database; assert
     the run report equals a committed expected JSON **exactly** (counts per rule, flags,
     gaps, rejected sessions), and that a second run changes nothing.
   - Demo script: seeds one instrument, POSTs a run through the API, prints the report and
     the rejected bars. This is the Mid demonstration; rehearse it on DEV.
   - Done when: the report matches exactly and the script runs from a clean database.
2. **Jenkins green on #57 to #65, merged in order** (section 2.1, section 9).
3. **Secret `MARKET_DB_PASSWORD`**, then DEV deployment and the smoke test through the
   gateway. The smoke script's API leg needs `SMOKE_ADMIN_USER` and `SMOKE_ADMIN_PASSWORD`
   in the deploy stage; without them it falls back to `docker exec ... run-once`, which does
   not prove the HTTP and JWT path.
4. **DEV end to end with the real key**: seed, trigger a run through the API on 3 symbols,
   check bars, report and events. Spend about 3 of the 45 hourly requests.
5. **Frontend pages** (none built): Instruments (list, add with the directory errors,
   retire), Market Data (bars and returns chart), Ingestion Runs (list, detail, rejected
   bars with rules), Audit Log. Use the OpenAPI document as the typed client source
   (export it in CI; plan I1-41). The frontend already has the shell, routing and
   `permissions.ts`; model the new pages on the existing ones and hide controls by
   capability (the server is the authority).
6. **CSP bug**: `frontend/public/_headers` and `frontend/nginx.conf` have
   `connect-src 'self'`, which blocks the API on the deployed site. It must allow the API
   origin (the tunnel address is dynamic: see how `config.json` is published by the
   deploy and decide between a wildcard for `*.trycloudflare.com` or a stable address).

### 10.2 Should do

7. **Replay sessions** (`POST /replay-sessions`, `GET /replay-sessions/{id}`; 422 for an
   inverted window) and the tick schema. The table `market_environment` exists. Needed by
   the simulation module; ask its owner what it needs before inventing fields.
8. **Operations** (plan section 8): metrics (runs by status, duration, rows by outcome,
   rejections by rule, vendor calls and latency, budget waits, circuit state, outbox
   backlog); logs must carry run id, instrument and vendor on every line (check; the key must
   never appear); `staging_bar` retention job (delete older than 90 days, as a scheduled
   CLI command); alerts once Grafana exists.
9. **Gate and calendar fixes found by real data testing** (small each; add a test first):
   - calendar default start: a window before the first session of the calendar library
   - a non string or malformed `date` value crashes the gate instead of rejecting the record
   - the `reject` outlier policy: exists as a setting, check it end to end
   - `returns.compute` uses `statistics.stdev`, which is the slow part (3 to 4 s a symbol);
     use a rolling sum of squares or `math.fsum` with Welford, then compare with pandas
   - returns continuity across a rejected session
10. **Gate property tests** (generated inputs: never publishes `high < low` or a price at or
    below 0; the report always adds up) using `hypothesis`; listed in the test plan, not
    written. Also confirm the rate limiter test "gives up instead of waiting an hour".
11. **Seed exchange labels**: the Nasdaq directory says WMT is XNAS and SPY, IWM, DIA, VTI,
    VOO, XLF, XLK, XLE, GLD are ARCX; `data/universe.py` says XNYS for all ten. The calendar
    stays XNYS, so returns are unaffected. Fix the universe **before the seed first runs in
    DEV**: the seed never overwrites and the unique key is symbol plus exchange, so changing
    it later creates duplicates. The ten differences are pinned in
    `tests/test_symbol_directory.py` (`EXCHANGE_DIFFERENCES`); update it with the fix.
12. **Backfill speed decision**: backfill and manual runs may use only 5 of the 50 hourly
    requests, so 40 instruments take about 8 hours. Options: seed fewer symbols for the
    demo, lower `QS_TIINGO_SCHEDULED_RESERVE` for the first backfill only, or accept it.

### 10.3 Could do (stretch, in the plan's cut order)

13. Correlation cache: a `correlation_matrix` table keyed by fingerprint, ETag headers, maybe
    Arrow output (the tech stack document lists them). The fingerprint is already there.
14. Tracing (I1-17): cross-cutting (`qs_template` and every service); needs agreement on the
    tool (OpenTelemetry is the usual choice) before anyone starts.
15. Symbol directory operations: schedule `scripts/fetch_symbol_directory.py`, set
    `QS_SYMBOL_DIRECTORY_DIR` in compose, optionally enforce the listing exchange.
16. Re-render the ERD SVG/PNG; correct the plan (the scheduler flag is
    `QS_INGEST_SCHEDULER_ENABLED`, not `QS_SCHEDULER_ENABLED`; update the status section).

---

## 11. Gaps and risks, stated plainly

- **Nothing of the new work is on `develop` and nothing is deployed.** Everything has been
  proven locally, not in CI or DEV.
- **The deployment wiring has only been reviewed and partially run** (image build,
  migration, seed and a run-once inside the image were run by hand; the compose file, the
  Jenkins stages, the smoke script and memory limits were not). Memory limits are guesses.
- **`relay`, and the worker against real Redis and Kafka**, have no automated test; they
  were exercised by hand once (41 outbox events published and read back from Redpanda).
- **The audit trail is trigger based for `instrument` only.** Run, item, bar and revision
  tables are not in `audit_log`.
- **All events go to one topic** (`quantsim.market.instrument`) because the template derives
  the topic from the aggregate type; consumers filter on `event_type`. A separate bars topic
  is a small template change if wanted.
- **One shared API key** for DEV, TEST, ACC and PROD means a runaway job in one environment
  can starve the others. The budget is counted in Redis, so it only protects across
  environments if they share one Redis; check whether each environment has its own (this
  was not verified). Treat 50 per hour as a hard shared limit and keep schedulers to TEST.
- **Vendor risk**: the free tier terms, one vendor, no second source. Outlier handling is
  flag and publish until a second vendor exists (decision D4).
- **Migration id `0002`** will collide with any other branch adding a migration.
- **Decimals and JSON**: never convert prices to float anywhere; the API returns strings and
  tests assert it.
- **Fixture data on DEV**: DEV is configured with the fixture vendor, so DEV holds 30 AAPL
  bars and 40 instruments, not real prices. TEST uses Tiingo.
- **The read API excludes instruments marked `is_fixture`** from data quality; nothing
  currently sets that flag.

---

## 12. Lessons learned (so you do not repeat them)

1. Run the exact CI commands before pushing (`mypy .`, `ruff check .`, `ruff format --check .`).
2. Test features against real data and together with the features they depend on; the
   smoke script and the run API disagreed on `symbols` versus `instrument_ids`, and only
   joining the branches showed it.
3. Hypertables ignore `TRUNCATE ... CASCADE` from the parent; clear every table in fixtures.
4. Windows and WSL: containers started without a restart policy disappear when the Docker
   daemon restarts. Use `--restart unless-stopped`. A background `wsl -d Ubuntu -e sleep` keeps
   the distribution attached; `wsl --shutdown` kills Jenkins builds.
5. Do not paste the API key anywhere; put it in an untracked file and read it into the
   environment for one command. It must never appear in a log, repr or error (the adapter
   uses `SecretStr`; keep it so).
6. When two pull requests touch `main.py`, `api.py` or the route and role matrix, expect a
   trivial "keep both sides" conflict.
7. Windows line endings: Git warns "LF will be replaced by CRLF"; the committed content is LF.

---

## 13. Verifying the module yourself in 15 minutes

1. Start a TimescaleDB container (section 8) and set `TEST_DATABASE_URL`.
2. `cd services/market && uv run ruff check . && uv run ruff format --check . && uv run mypy . && uv run pytest -q`
3. Record the corpus (needs the key) and run `uv run pytest tests/realdata -m realdata`
   (about 3 minutes).
4. Run the by hand stack in section 8; then `GET` the run and the bars through the API.
5. With the key: `QS_VENDOR=tiingo QS_TIINGO_API_KEY=... python -m qs_market run-once ... --symbol AAPL --symbol NVDA`
   for a small window that includes 2024-06-10; expect the 10 for 1 split stored once.
