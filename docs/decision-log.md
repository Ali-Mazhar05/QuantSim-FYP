# Decision log

Questions that came up while building, and what was decided, with the reasons. It exists so that
anyone can see **why** something is the way it is, and change it knowing what depends on it.

Rules: one entry per question; append, never delete. To change a decision, add a new entry that
supersedes the old one, mark the old one **Superseded by DL-nnn**, and update everything under its
**Affects**. A decision that needs an architecture-level record also has an ADR in `docs/adr/`; this log
holds the smaller choices an ADR would be too heavy for.

**Status:** *Adopted*: taken by the owning lane so work could continue, open to review by the person named;
*Resolved*: settled by evidence in the code or plan, nothing to review; *Open*: needs a person.

Sources are named where a reason rests on them: the submitted Mid Report (**Report**), the Iteration 2
plan and lane guides (**Plan**), the ingestion plan (`docs/ingestion-plan.md`), and the code on
`develop` (file names).

## Index

| ID | Topic | Status | Review by |
|---|---|---|---|
| DL-001 | The median path a portfolio binds to | Adopted | Lane A |
| DL-002 | A simulation run as an environment | Adopted | Lane A |
| DL-003 | The replay clock | Adopted | Lane A |
| DL-004 | The replay fingerprint | Adopted | Lane A |
| DL-005 | Bars with missing adjusted prices | Adopted | Lane A |
| DL-006 | A symbol with no bar on a session | Adopted | Lane A |
| DL-007 | What `session` means | Adopted | Lane A |
| DL-008 | Paging of the tick feeds | Adopted | Lane A |
| DL-009 | OU simulated on log price | Adopted | Lane C |
| DL-010 | Seeding and shards | Adopted | Lane C |
| DL-011 | Repairing a correlation matrix | Adopted | Lane C |
| DL-012 | A correlation matrix with unavailable cells | Adopted | Lane C |
| DL-013 | Path storage limit | Adopted | Lane A |
| DL-014 | Path values in a plain table | Adopted | team |
| DL-015 | Service tokens for the feeds | Resolved by ADR 09 | Lane A |
| DL-016 | The price window a calibration reads | Adopted | Lane C |
| DL-017 | Snapshotting ticks at activation | Adopted (deferred) | Lane A |
| DL-018 | Synthetic ticks are single-price bars | Adopted | Lane A |
| DL-019 | The timestamp of a tick | Resolved | |
| DL-020 | Stubs on DEV for the feeds | Adopted | Lane A |
| DL-021 | The shape of the fixtures | Adopted | Lane A |
| DL-022 | The answer of activation | Adopted | Lane A |
| DL-023 | Where the consumer contract tests live | Open | Lane A, Lane C |
| DL-024 | Metrics, queue depth and worker limits | Open | Lane A |
| DL-025 | The simulation package name | Resolved | |
| DL-026 | Lane branch protection | Open | Lane A |
| DL-027 | Pull requests while Jenkins is down | Adopted | team |
| DL-028 | Grouping work into fewer pull requests | Adopted | team |
| DL-029 | Environments that are not ready | Adopted | Lane A |
| DL-030 | What activation does | Adopted | Lane A |
| DL-031 | How the feed reads a large window | Adopted | team |
| DL-032 | Replay session routes and who may use them | Adopted | Lane A |
| DL-033 | What a replay session stands on | Adopted | Lane A |
| DL-034 | Position over polling, not SSE | Adopted | team |
| DL-035 | One calibration resource from queued to stored | Adopted | team |
| DL-036 | What a calibration refuses, and where | Adopted | team |
| DL-037 | Calibration without a price source or a fit | Adopted | team |
| DL-038 | The shape of a run request and what a run starts from | Adopted | team |
| DL-039 | How a run is stored and reproduced | Adopted | team |
| DL-040 | VaR and CVaR before K6 is installed | Adopted | team |
| DL-041 | What the demo-size run costs, and why | Adopted | team |
| DL-042 | The read API: ticks, dates, fingerprint, lists, quantiles | Adopted | team |
| DL-043 | Stress scenarios: what they change and how a stressed run is made | Adopted | team |

---

### DL-001 The median path a portfolio binds to

- **Asked:** what is the "median path" of a run? The demo binds a portfolio to it (Plan, demo spine step 5; B-US-09).
- **Decided:** rank the paths by the terminal value of the equal-weighted basket of normalised prices
  (`S_T / S_0`, averaged over the run's instruments); take the lower median rank; ties go to the lowest
  path index. Stored on the run as `median_path_index`; a completed run must have one.
- **Why:** a per-step median is not a path, so it cannot be traded. The run exists before any portfolio, so
  the rule cannot use a portfolio's weights; equal weights are the neutral choice and need nothing else.
  The rule is deterministic and the path regenerates from the seed (Report 9.5 determinism; B-NFR-05).
  Ranking one instrument only would ignore the others in a multi-name run.
- **Alternatives rejected:** median of the first instrument (ignores the rest); the path closest to the
  per-step median (not unique, needs a distance choice); a random path (not reproducible).
- **Affects:** ADR 03; `run.median_path_index` and its CHECKs in `simulation_db`; `contracts/README.md` section 3;
  the run list and detail models (`api_runs.py`); the synthetic fixture.
- **If changed:** only the code that computes the index (B16) and ADR 03; consumers read the index, not the rule.

### DL-002 A simulation run as an environment

- **Asked:** how does a finished run act as an environment for Lane A's picker?
- **Decided:** by identity, with no extra table: a completed run is served with `env_type: "synthetic"` and
  `env_id` equal to the run id, a path chosen with `?path=`. The picker lists
  `GET /api/simulation/runs?status=completed`.
- **Why:** the tick contract already gives `env_id` as "the run id for synthetic" (Plan, Lane B guide C1) and
  Lane A's guide fills its picker from exactly these two lists. Creating a market environment row for each
  run from the simulation service would be a write across a service boundary, which the architecture forbids
  (reads cross services, writes stay with the owner). A run can number in the thousands; environment rows
  are the user's declared universes.
- **Open follow-up:** a synthetic market *environment* (declared in market) and the *runs* made on it are not
  linked in `simulation_db` today. If the Results page needs "runs of this environment", add a nullable
  `environment_id` to `run`.
- **Affects:** ADR 01 and 03; `contracts/README.md`; C2 run routes.
- **If changed:** a simulation-to-market write would need a new event and a consumer in market; do not
  do it without a new ADR.

### DL-003 The replay clock

- **Asked:** how is the replay clock kept? The plan gives only the test: 5x for 2 s advances 10 sessions,
  and a reload resumes at the server position (B-FR-06).
- **Decided:** store an anchor session index, the server time of that anchor, the speed (1, 5 or 20) and
  the state; compute the position on read: `min(anchor_index + floor(elapsed_seconds x speed), last_index)`
  while playing. Pause, speed change and seek each write a new anchor. 1x is one session per second.
- **Why:** it survives a restart, has no background task (the deployment is one laptop-hosted stack on a free
  tier), gives every tab the same answer, and is testable with an injected clock. A ticking background task
  would lose its position on restart and drift between tabs.
- **Affects:** ADR 06; B13 (`replay_session` table and its CHECKs); the Replay page.
- **If changed:** the API surface (play, pause, speed, seek, read) stays the same.

### DL-004 The replay fingerprint

- **Asked:** how is `source_fingerprint` computed, and what does it change on? The guide says "only when a
  bar revision lands".
- **Decided:** xxh3 (128 bit) over the ordered served values `(instrument, session, revision, adjusted open,
  high, low, close, volume)` of the instruments in the window. It changes on a revision **or** when the
  vendor restates an adjusted price in the window; not for other instruments or dates outside it.
- **Why (verified in the code):** `content_hash` leaves adjusted prices out on purpose (`cleaning.py`;
  ingestion plan D18: they are restated at every dividend or split), and the pipeline then updates the
  adjusted columns **in place without a revision** (`runner.py`). A fingerprint from revisions alone would
  stay the same while the tick prices change. The Report promises that replaying an identical stored
  dataset gives the same ordered event sequence (9.5); a restated dataset is a different dataset, and the
  fingerprint is what tells the consumer so.
- **Affects:** ADR 08; `qs_market/feeds.py` (`fingerprint`); B-FR-02 wording; C1 README.
- **If changed:** the contract text (what the fingerprint changes on), B12 tests, and every stored run that
  recorded a fingerprint.

### DL-005 Bars with missing adjusted prices

- **Asked:** what if a bar in the window has no adjusted value (the columns are nullable)?
- **Decided:** the environment cannot be activated and its feed refuses with 422 `missing_adjusted_prices`
  and counts per symbol. Raw prices are never substituted. On the wire the problem type is spelled
  `urn:quantsim:problem:missing-adjusted-prices` and the counts are `missing` (`{"AAPL": 3}`); see
  `contracts/README.md` section 3.
- **Why:** an adjusted price depends on corporate actions that come **after** a session, so a missing one
  cannot be rebuilt, and a raw price before a split is on a different scale from adjusted prices after it:
  mixing them draws a fake crash. The platform already treats adjusted close as the price basis
  (`price_basis: adjusted_close` in the metrics API; the Report says the vendor adapter "separates raw and
  adjusted fields" in the stored market series).
  Refusing loudly matches how the platform treats other bad data (the database and the gate refuse).
- **Affects:** ADR 08; `feeds.build_ticks` (`MissingAdjustedPrices`); B12 activation and feed.

### DL-006 A symbol with no bar on a session

- **Asked:** what does the feed do when one instrument has no bar on a session?
- **Decided:** that symbol has no tick on the session; `seq` stays gap-free over the ticks emitted; the other
  symbols are unaffected; activation records `missing_session_count`. The engine must tolerate an absent
  symbol.
- **Why:** the ingestion plan records such sessions as data gaps and does not fill them ("missing session:
  record", `data_gap`); filling would invent prices and let a strategy trade on data that never existed.
  The Report says malformed observations are deterministically rejected or flagged (9.5), not repaired.
- **Affects:** ADR 08; `contracts/README.md` (Order); Lane A's adapter.
- **If changed:** Lane A would need a flagged filler tick in C1 (additive: a `filled` field).

### DL-007 What `session` means

- **Asked:** what is the `session` field?
- **Decided:** the zero-based index of the session among the sessions present in the environment; for a
  synthetic run, the step from 0. `session_date` is optional for replay.
- **Why:** Lane A's engine works per session ("one transaction per session; the strategy sees history up to
  t", Plan engine loop) and the replay clock counts sessions (DL-003); an index serves both and also fits
  synthetic steps, which have no calendar meaning in the models. A date alone would not give a dense,
  gap-free ordering.
- **Affects:** C1; `feeds.build_ticks`; the replay clock.

### DL-008 Paging of the tick feeds

- **Asked:** page size and shape for `GET .../ticks`.
- **Decided:** pull by `after_seq` (default 0); `limit` default 500, at most 2000; body
  `{items, next_after_seq}` with `next_after_seq` null on the last page; header `X-Source-Fingerprint`.
- **Why:** the market service already pages every list with `DEFAULT_LIMIT = 500` and `MAX_LIMIT = 2000`
  (`api_data.py`) and has a measured test (first page of 2000 under a second); one convention per service is
  easier to consume and to test. A tick is about 450 bytes in the fixtures, so 2000 is under 1 MB. A year of
  40 instruments (10,080 ticks) is about five pages, far inside A-NFR-01 (40 x 252 in 60 s).
  *First draft used 1000 and 5000; changed after finding the existing convention.*
- **Affects:** ADR 01; C2 (both services); `contracts/README.md`.

### DL-009 OU simulated on log price

- **Asked:** is the OU process on price or on log price?
- **Decided:** on log price, published as `exp(X)`.
- **Why:** Lane C's calibration is `fit_ou(log_prices, dt)` (Lane C guide, K5), so the generator must simulate
  the process that was fitted, or the stored parameters mean something else. It also keeps prices positive.
- **Affects:** ADR 02; `generators/ou.py`; B15 and B16.

### DL-010 Seeding and shards

- **Asked:** how are random streams assigned so a run is identical on 1, 2 or 4 workers?
- **Decided:** fixed shards of 250 paths; shard `k` draws from three streams built directly from
  `SeedSequence(seed, spawn_key=(k, i))` (normals, Poisson counts, jump sizes). The instrument list is part
  of the run, so a different list is a different run.
- **Why:** B-NFR-04 requires the same output for 1, 2 and 4 workers and B-NFR-05 the same seed, same
  statistics; a stream that depends only on `(seed, shard, stream)` cannot depend on the worker count or
  on the order shards run. Tested with real worker processes.
- **Affects:** ADR 02; `domain/sharding.py`.

### DL-011 Repairing a correlation matrix

- **Asked:** how is a matrix that is not positive definite repaired?
- **Decided:** clip eigenvalues at 1e-8, rescale to a unit diagonal, and record whether it was repaired, the
  smallest eigenvalue before and the size of the change on the run.
- **Why:** the plan requires the nearest-PSD repair and its record; this does it with numpy only (no new
  dependency), keeps definiteness (a congruence rescale does), and the record lets a result be audited.
- **Affects:** ADR 02; `domain/correlation.py`; `run_correlation` columns.

### DL-012 A correlation matrix with unavailable cells

- **Asked:** the market correlation API returns `null` cells with a reason (`insufficient_observations`,
  `constant_series`); what does a run do with them? (Raised while reading the API for B16.)
- **Decided:** a run whose matrix has any unavailable cell is refused with 422 naming the pair and the
  reason; nothing is substituted.
- **Why:** a correlation that was not computed cannot be invented without changing the risk the run claims
  to measure, and the API already says why the value is undefined. A later option (an explicit,
  user-chosen fallback) can be added without breaking this.
- **Affects:** B16 (not built yet); the run submit errors.

### DL-013 Path storage limit

- **Asked:** how many values may a run store in full? ADR 03's default said 1,000 paths x 252 steps without
  saying per how many instruments.
- **Decided:** store every value when paths x steps is at most 252,000 per instrument **and** there are at
  most 10 instruments; otherwise store the seed, configuration and per-step quantiles and regenerate paths.
  Enforced for the per-instrument part by a CHECK.
- **Why:** the demo is 5 names x 1,000 x 252 = 1.26 million rows, which a laptop-hosted database takes with
  `COPY`; 40 names would be 10 million with no demo benefit (the 40-name universe is for TDA, which reads
  market data). Regenerating from a fixed seed is already a tested requirement (B-FR-14), so nothing is lost.
- **Affects:** ADR 03; `run_full_storage_within_rule`; B16.

### DL-014 Path values in a plain table

- **Asked:** the guide says `path_value` is a hypertable.
- **Decided:** an ordinary table keyed by run, instrument, path and step, with a second index by step.
- **Why:** a hypertable needs a time or integer partition column that serves the queries, and the two real
  access patterns (all steps of one path; one step across paths) are served by the key and the index;
  `COPY` already gives the bulk speed. The ADR wins over the guide.
- **Affects:** ADR 03; `path_value`.
- **If changed:** revisit if a measurement on the demo run shows a problem.

### DL-015 Service tokens for the feeds

- **Asked:** do K3 service tokens pass the existing `Authenticator`, or does `libs/qs_template` change?
- **Resolved (ADR 09, Lane A, 2026-11-20):** a platform-issued service token (`kind: service`, subject
  `service:<name>`) passes the existing `Authenticator` as a read-only service principal, like a viewer.
  So the feed, the bars and the correlation API answer it, and activation and replay sessions refuse it.
  `libs/qs_template` did not need a Lane B change. Tested in
  `services/market/tests/test_service_token_access.py`; the simulation service sends the token through
  the K3 service client (`composition.market_sources`).

### DL-016 The price window a calibration reads

- **Decided:** adjusted closes from the market `bars` endpoint (and `returns` for log returns); the input
  fingerprint is xxh3 over the ordered `(session, adjusted close, revision)`.
- **Why:** the platform's price basis is adjusted close (see DL-005); both endpoints exist and are reviewed.
- **Affects:** B15.

### DL-017 Snapshotting ticks at activation

- **Asked:** should activation copy the ticks, so a replay cannot change if the vendor restates prices?
- **Decided:** not now. Build the feed behind one function so a snapshot can replace its query later.
  **Trigger:** a rehearsal on TEST shows a replay changing between two runs, or a demo that must not drift.
- **Why:** the Report's promise is determinism for an *identical stored dataset* (9.5), and the fingerprint
  (DL-004) identifies the dataset, so the promise holds without a snapshot. A snapshot adds a table and about
  a day of work and is additive, so it can be added without changing the contract. Cheaper mitigation for a
  demo: show the fingerprint on the Replay page and avoid re-ingesting the demo names in the last days.
- **Affects:** B12 design only.

### DL-018 Synthetic ticks are single-price bars

- **Asked:** what are open, high, low, close and volume of a synthetic tick?
- **Decided:** one price per step: `open = high = low = close`, `volume = "0.00000000"`.
- **Why:** the models (GBM, OU, Merton) generate one price per step (Report FR-SIM-02); an intraday range
  would need another stochastic model that nothing in the plan calibrates or validates, and any such range
  would be invented structure that results then depend on. With single prices a market order filled at the
  next session's open fills at the next step's price, one step after the decision, which is what Lane A's
  rule requires (ADR 04: next session's open) and cannot look ahead.
- **Consequence for Lane A (please read):** a **limit order** can only fill when the step price crosses it;
  and **volume-based slippage** (`bps x qty / bar volume`, Lane A guide A-FR-09) is undefined on a synthetic
  tick because the volume is zero. Use fixed-bps slippage on synthetic runs; the demo uses fixed 10 bps, and
  the plan already puts volume-based slippage first in the cut order.
- **Affects:** C1 README; the synthetic fixture; B16/B18 tick feed; Lane A's slippage on synthetic markets.
- **If changed:** a bar-shaped synthetic tick would be an additive change (high and low differing), but the
  generator and its tests would need a range model first.

### DL-019 The timestamp of a tick

- **Decided:** the session close in UTC (21:00 in winter, 20:00 in summer for NYSE); synthetic steps use
  real NYSE sessions and closes.
- **Why (verified):** `bar.ts` is stored as the session close by `calendars.session_close`
  (`cleaning.py`); using the same source keeps replay and synthetic ticks ordered in time alike.

### DL-020 Stubs on DEV for the feeds

- **Asked:** the plan puts fixture-serving stubs on DEV by 25 Nov for Lane A's HTTP adapter. (The market feed has since been built for real in B12; this now applies to the simulation routes only.)
- **Decided:** no stubs; the feed, activation and run routes answer an explicit 501 until B12, B16 and B18
  build them, and Lane A reads the C3 fixtures meanwhile.
- **Why:** DEV was unreachable when this was decided (Jenkins host offline), so a stub there could not be
  used anyway; the real routes replace a stub within the same work, so a stub is built twice; and a stub
  would need the fixtures packaged into each service image. The contract is still final and tested
  (paths, parameters, models, errors).
- **If needed sooner:** say so; a stub is a small route reading the fixture file.

### DL-021 The shape of the fixtures

- **Decided:** `replay_ticks_2020.json` holds the whole feed (1,265 ticks) as `items` with the environment
  description; `synthetic_ticks.json` holds `paths[].items`; every file has a `meta` block.
- **Why:** a file adapter reads one file; `items` has the same shape as an API page, so one parser serves
  both; consumers already ignore unknown fields (change rule), so `meta` costs them nothing. The API pages
  the same data by DL-008.
- **Known limits:** the correlation fixture has six names (the recorded corpus holds six); regenerated for
  the 40-name universe once Lane C's data is loaded. The synthetic fixture uses a self-contained GBM,
  because the real generators are on the lane branch and a `develop`-bound branch cannot import them;
  regenerate from `qs_simulation` once it is on `develop`.

### DL-022 The answer of activation

- **Decided:** `{environment_id, status: "active", source_fingerprint, missing_session_count, activated_by,
  activated_at}`; 422 `unsupported-frequency` for hourly or tick, 422 `not-a-replay-environment` for a
  synthetic one.
- **Why:** activation freezes the fingerprint and records who and when (Plan, B12), as the audit trail does
  elsewhere in the platform; `missing_session_count` is the transparent side of DL-006. Hourly and tick
  environments cannot be replayed (B-FR-03); a synthetic environment has no replay feed in market.

### DL-023 Where the consumer contract tests live

- **Status: Open.** Lane A writes consumer tests for C1 and C2 and Lane C one for C4; they run in Lane B's
  pipeline (Plan; B-NFR-12).
- **Working assumption:** a `contracts/` test collection included by the market and simulation test runs;
  `services/market/tests/contract_support.py` shows the validation to copy. Lane A and Lane C to confirm
  where theirs live.

### DL-024 Metrics, queue depth and worker limits

- **Status: Open (Lane A).** Whether the team has a metrics stack for job duration and queue depth, and who
  sets worker memory and the reserved API core in compose (Lane A owns compose).
- **Working assumption:** structured logs per job and an admin read route for queue depth; limits in compose.

### DL-025 The simulation package name

- **Resolved by evidence:** the scaffold on `develop` generated `qs_simulation`, which the Lane B code uses.

### DL-026 Lane branch protection

- **Status: Open (Lane A / repository admin).** `lane/b-simulation` was unprotected when checked on
  2026-11-17; the plan requires protection (a pull request and a passing check) before the contract freeze.

### DL-027 Pull requests while Jenkins is down

- **Decided:** every pull request body says what was run locally (commands and counts) and that Jenkins did not
  run; the code gate is `preflight.sh` run in Docker. Jenkins must be green before a merge once it is back.
- **Why:** the Report names Jenkins build #47 as proof of deployment and the team already saw that status
  drift (the `develop` head showed `error`); a PR must not claim a check that did not run.

### DL-028 Grouping work into fewer pull requests

- **Decided (team, 2026-11-18):** related tasks go on one branch with one logical commit each, instead of
  one pull request per task or per ADR; a pull request still has one clear purpose, its tests and a
  description that lists its commits. This replaces the guide's "one ADR per pull request" and "about
  400 lines".
- **Why:** reviewing is the bottleneck with three people; commits keep the step-by-step reading.

### DL-029 Environments that are not ready

- **Asked:** what does the feed or activation do for an environment some of whose instruments have no data
  yet (status `draft`)? Found while building B12.
- **Decided:** both refuse with 422 `environment-not-ready`; a `ready` or `active` environment is served.
- **Why:** `draft` means some instrument has no clean bar in the window (`market_environment` status, set
  when the environment is created). A feed with a whole instrument missing would hand an engine a market
  that is not the one the user declared; refusing says so. Reading and activating a ready environment is
  unchanged. A partly filled window of a *ready* environment is served and its gaps are reported
  (DL-006).
- **Affects:** `replay.check_replayable`; the C2 errors in `contracts/README.md`.

### DL-030 What activation does

- **Asked:** what exactly happens on `POST /environments/{id}/activate`? The plan says it freezes the
  fingerprint and sets the status.
- **Decided:** in one transaction: compute the fingerprint of the window, count the sessions on which an
  instrument has no bar, upsert one `environment_activation` row (fingerprint, missing count, who, when),
  and set the environment's status to `active`. Repeating it re-freezes (a new fingerprint, a new time,
  still one row). Quants and admins only. The status change is audited like any other change to an
  environment (who, when, before and after); the frozen fingerprint is in its own row.
- **Why:** one frozen value per environment is what a consumer needs to compare with each page (DL-004);
  re-freezing is how a user accepts restated data on purpose. `active` already exists in the status check
  and was reserved for "used by a replay or a run". A separate audit trigger on the new table would need
  the audit feed (which formats known tables) to learn it; the status change already records the actor.
- **Affects:** migration `0004`; `environment_activation`; ADR 08 (fingerprint frozen at activation).

### DL-031 How the feed reads a large window

- **Asked:** a window can hold 100,000 bars; how does a page of 500 to 2,000 ticks stay inside the 2 second
  target (B-NFR-02)? Found by measuring: the first version took 6.2 s per page for 40 instruments over
  2,900 sessions.
- **Decided:** PostgreSQL writes each bar's canonical line (instrument, session, revision and the five
  adjusted values at column scale) and flags gaps; Python only hashes the lines; only the rows of the
  page are fetched as values. Both queries run in one `REPEATABLE READ` transaction. The pure
  `feeds.fingerprint` stays the reference, and a test holds the database's lines and the pure core equal
  on the same rows.
- **Why:** the cost was moving every value of the window into Python on every page, then formatting and
  hashing it. Rendering text in the database and hashing strings is an order of magnitude cheaper and keeps
  the exact fingerprint of ADR 08 (it still changes on a revision or a restated price). One snapshot means a
  restatement that commits during a request cannot give a page and a header from different data.
- **If it is still too slow later:** cache the fingerprint per environment against a database-side
  checksum of the window; do not weaken what the fingerprint covers.
- **Measured after that, three more changes:** (1) both queries sort symbols by code point (`COLLATE "C"`),
  as `feeds.ordered` does, so a database locale that ignores punctuation cannot reorder `BRK.B` and `BRKA`
  (a test holds it) and the sort is cheaper; (2) the window query groups by session, so a window comes back
  as about 2,900 texts, not 116,000 rows; (3) a page reads only the sessions its seq range covers, found
  from the per-session bar counts, instead of sorting the whole window for an `OFFSET`. A cached
  fingerprint was not built: a restated price changes the data without a trustworthy change marker, so no
  cheap signal was provably exact.
- **Affects:** `qs_market/replay.py`, `feeds.canonical_line` and `feeds.fingerprint_of_lines`.

### DL-032 Replay session routes and who may use them

- **Asked:** which routes drive a replay clock, and which role may control it (B-FR-06, B-US-05)? The plan
  names `POST /replay-sessions` and `GET /replay-sessions/{id}` and says control needs the quant role.
- **Decided:** `POST /replay-sessions` (create, paused at the first session), `GET /replay-sessions?environment_id=`
  (newest first), `GET /replay-sessions/{id}`, and one `POST /replay-sessions/{id}/control` with a body
  `{action: play | pause | speed | seek, speed?, index?}`. Reads need `view_market_data` (every role);
  create and control need `create_market_environments` (quant, admin), so an analyst and a viewer get 403.
  Speed is 1, 5 or 20 (422 otherwise; the database also refuses). Seek clamps to the first and last session.
  Repeating a state (play while playing, the same speed, pause while paused) changes nothing, so a double
  click cannot lose the fraction of a session that has elapsed. Every change is audited with who made it.
- **Why:** the Tech Stack document already describes a single `.../control` route; one route with an
  `action` keeps the typed client small. The list route is what lets a reloaded page find the session it was
  driving. No new capability was added, because the capability list lives in `libs/qs_template` (Lane A).
- **Alternatives rejected:** a route per verb (four routes for one idea); a new `control_replay` capability
  (a change to Lane A's file for no new distinction between roles).
- **Affects:** `qs_market/api_replay.py`, `replay_sessions.py`, the role matrix test, the Replay page (B20).

### DL-033 What a replay session stands on

- **Asked:** which environments can have a session, and what does a session pin?
- **Decided:** only a daily replay environment that is **active** (activated, so its data is frozen): any
  other gets 422 `environment-not-active` (a draft, hourly or synthetic environment keeps the 422 of DL-029).
  The session stores the activation's fingerprint and the number of sessions in the window at creation. The
  stored count lets the database bound the anchor (`0 <= anchor_index < session_count`). Every read returns
  `source_fingerprint` (pinned) and `current_fingerprint` (the environment's frozen value now), so a page can
  show that the environment was activated again; changes to the data without a new activation show on the
  `X-Source-Fingerprint` header of each page of ticks, as before. Every read also returns the trading date at
  the position and the `server_time` the position was computed at, so a page can interpolate between polls.
- **Why:** a replay of data that is not frozen could change under the viewer; computing the live fingerprint
  of a 100,000-bar window on every poll would cost about a second (DL-031), so the cheap frozen value is the
  one compared. The date lookup is one grouped read of the window's dates and stays under half a second on 40
  instruments over 2,900 sessions (tested).
- **Affects:** `replay_session` (migration 0005), `replay_sessions.py`, ADR 06 note.

### DL-034 Position over polling, not SSE

- **Asked:** is the stream of positions (B-FR-07, Last-Event-ID resume) built? The plan lists it first in the
  cut order and says polling is accepted if it is cut.
- **Decided:** cut. Clients poll `GET /replay-sessions/{id}` every 500 ms to 1 s, and animate between polls
  from `position`, `speed` and `server_time`.
- **Why:** the position is a pure function of stored values, so a poll is cheap and always right, survives a
  restart and works through the Cloudflare tunnel; a long-lived stream adds reconnect state for no change in
  what the page can show. B-FR-07 stays open as a cut item.
- **If reversed later:** a stream would only repeat the poll answer; no route changes.

### DL-035 One calibration resource from queued to stored

- **Asked:** the plan says `POST /calibrations` answers 202 and the job completes asynchronously, and also
  that a refusal is "a 422". A 202 cannot carry a later 422, so where does a client see the outcome?
- **Decided:** the calibration's id is its job's id. `POST` answers 202 with that id and a `Location`;
  `GET /calibrations/{id}` returns one shape at every stage: `status` is `queued`, `running`, `succeeded`
  (with the stored `calibration`), `refused` (with `refusal: {http_status: 422, code, reason}`) or `failed`
  (with the job's `error`). A refusal is a result of the job, so the poll answers 200; the 422 is the
  `http_status` inside the refusal. Reads are open to every signed-in role, as the plan's other reads are;
  the list and its filters come with B18.
- **Why:** one id for the whole life of the work needs no second lookup, survives a reload and follows the
  K1 job table the service already has. Returning 422 from a GET of an existing resource would make a
  finished refusal look like a broken request.
- **Alternatives rejected:** a separate job id and calibration id (two ids to keep); 422 on the poll;
  running the fit inside the request (breaks the 800 ms limit and K1).
- **Affects:** `qs_simulation/calibrations.py`, `api_calibrations.py`, the Calibrations page (B20).

### DL-036 What a calibration refuses, and where

- **Asked:** "refuse under 60 sessions before calling K5": 60 sessions are 59 returns, and K5 refuses fewer
  than 60 returns. Which check owns which number?
- **Decided:** the service refuses fewer than 60 **sessions** (`insufficient_history`) before any model is
  asked. A window of exactly 60 reaches the model, which may refuse it in its own words
  (`fit_refused`); 61 sessions are the fewest that give a stored fit. The service also refuses a window with
  a session twice or a close without a logarithm (`invalid_prices`), a bar without an adjusted close
  (`missing_adjusted_prices`, never a raw price), an unknown instrument (`instrument_not_found`), and a fit
  that cannot be stored (a parameter or the log-likelihood or AIC that is not finite, or fewer than 60
  observations, which the table also forbids). A standard error K5 could not compute (NaN) is stored as null.
  A refusal is returned as the job's result and is not retried; an unreachable price source raises and K1
  retries it, then marks the job failed with the error.
- **Why:** the plan's number is a floor on what is asked of K5, K5's own floor is on returns; stating both
  keeps each owner's rule where it belongs and the boundary is tested, not assumed.
- **Affects:** `domain/calibration.py`, `calibrations.py`, the `calibration` table's CHECKs.

### DL-037 Calibration without a price source or a fit

- **Asked:** K3 (service tokens) and K5 (fits) are not on `develop`. What does the service do now?
- **Decided:** the market adapter reads through a one-method `Getter` (`get_json`), which K3's service
  client has, so nothing here imports K3; wiring it into `build_app` is a small follow-up once K3 merges.
  Until then a service built without a price source answers 503 `calibration-unavailable` instead of queueing
  work nobody does. A model with no fitting code (Merton until K5 delivers it, or every model while
  `qs_quant` is absent) answers 501 at submit. Tests use a reference GBM written from Lane C's formula (7.2)
  as the stand-in for K5. Idempotency keys are the caller's own: the queue's keys are global, so the service
  prefixes the caller's user id.
- **Why:** faking a fit would put invented numbers in a risk model; refusing honestly keeps the contract and
  the page work unblocked. Scoping keys stops one user's key from returning another user's job.
- **Not covered until K3 and K5 land:** the circuit breaker and retry of the real client against a live
  market service (tested here on the adapter's side with injected failures), a real K5 equality test, the
  service-token path (D14).
- **Affects:** `adapters/`, `main.build_app(price_source=, calibrator=)`.

### DL-038 The shape of a run request and what a run starts from

- **Asked:** what does `POST /runs` take, and where do the start prices, the correlation matrix and the seed
  come from? The plan says "validate limits, insert run with idempotency key, enqueue job".
- **Decided:** `{model, instruments: [{instrument_id, calibration_id}], n_paths, n_steps, seed?,
  correlation_window?}`. Every calibration must exist, belong to its instrument, be of the run's model and have
  converged (422 naming each problem). Limits: 20 to 100,000 paths (20 is the least the VaR/CVaR sample
  accepts), 1 to 2,520 steps, 1 to 40 instruments each once, and at most `max_run_values` prices
  (paths x steps x instruments, 60 million by default, about 480 MB) so one run cannot exhaust a worker (422
  `run-too-large`). The start price of each instrument is its adjusted close on the last session of its
  calibration window, read when the job runs and written to 10 decimals before anything is generated. The
  correlation matrix is measured over `correlation_window`, by default the overlap of the calibration windows;
  a single instrument needs no matrix. The seed is drawn by the server when left out and is always returned.
  Roles: quants and admins launch (`launch_simulations`); every signed-in role reads.
- **Why:** a calibration already names the instrument, the model and the window the parameters are valid
  for, so the run neither re-fits nor guesses; the last calibrated close is the price the parameters describe.
  Rounding the start price before generating is what lets a stored run be regenerated exactly (DL-039).
- **Affects:** `qs_simulation/runs.py`, `api_runs.py`, the Configure page (B20).

### DL-039 How a run is stored and reproduced

- **Decided:** the run's id is its job's id; the run row is inserted at submit with its storage mode decided
  (DL-013), and the job writes the instruments, the correlation, the statistics, the per-step quantiles, the
  paths (when stored in full), the `completed` status and the `sim.completed` event in **one transaction**, so
  a run is complete and announced or not there at all. A job killed before that leaves nothing and its re-run
  gives identical statistics. Progress goes out as `sim.progress` events about every tenth. A refusal (an
  undefined correlation cell, DL-012; a start price that does not exist; an instrument the market does not
  know; prices that cannot be stored) marks the run `failed` with `code: reason` and a `sim.failed` event and is
  not retried; any other failure is retried by the queue, and on the last attempt the run is marked failed
  with the error. `run_correlation.matrix` holds the matrix **as given, before repair**: the repair is
  deterministic and recorded, so the stored seed, parameters, start prices and matrix regenerate every path bit
  for bit (tested for all three models and for a matrix that needed repair). Quantiles are stored for every run,
  the paths only when small. One instrument needs no correlation call.
- **Why:** a half-written run would show statistics without paths, or paths a portfolio cannot bind to. The
  stored matrix before repair, not after, is what makes regeneration exact: repairing an already repaired
  matrix can differ in the last bits.
- **Affects:** `runs.py`, `run_correlation`, B18 (`GET /runs/{id}/ticks` regenerates from these).

### DL-040 VaR and CVaR before K6 is installed

- **Asked:** K6 (`var_cvar`) is not delivered. Fail runs until it is, or compute it here?
- **Decided:** the statistics go through a `RiskCalculator` port. It uses K6 when `qs_quant.metrics` is
  installed, and otherwise the formula of Lane C's specification (7.6): `q = quantile(R, 1 - alpha)` by linear
  interpolation, `VaR = -q`, `CVaR = -mean(R | R <= q)`, both positive losses, at least 20 returns. The version
  (`reference-7.6` or K6's) is written in the `sim.completed` event and the job's log line. A test holds the
  two equal on the same returns the day K6 is installed (it is skipped until then).
- **Why:** the formula is fully specified and ten lines long, so a run can complete end to end now; a run
  that could not complete would block the results, the pages and the demo for a ten-line function. K6 stays
  the owner of the definition (tracker I-04).
- **Affects:** `adapters/risk.py`, B16 statistics.

### DL-041 What the demo-size run costs, and why

- **Measured** on the development machine (PostgreSQL 17 with TimescaleDB in a container under WSL): the demo
  run, 5 instruments x 1,000 paths x 252 steps, answers the submit in 55 to 97 ms and completes in about 60 to
  75 s, and stores 1,260,000 path values. Generating and summarising the paths takes a few seconds; the rest is
  the database.
- **Why:** the composite foreign key from `path_value` to `run_instrument` is checked row by row by
  PostgreSQL. The same 252,000 rows take 13.6 s with the key and 2.0 s without it (about 1.2 s with the primary
  key alone), so 1.26 million rows spend about a minute on the key. Formatting prices as CSV text for `COPY`
  (rather than building a decimal per value) was done and helps less than the key costs.
- **Decided:** keep the key: it is what guarantees a stored path belongs to a run's instrument and goes with it.
  B-NFR-03 asks that the 10,000 x 252 run completes and is measured, not for a time; Hamza's performance study
  records that one. The run page shows progress while it works.
- **If it must be faster** (the end-to-end spine waits on it): replace the key with one set-based check per
  statement (a constraint trigger over the inserted rows), which keeps the guarantee for about the cost of the
  insert; or store less (quantiles only). Neither is built; tracker I-31.
- **Affects:** `runs._store`, `path_value`, the B22 timeouts.

### DL-042 The read API: ticks, dates, fingerprint, lists, quantiles

- **Asked:** how does `GET /runs/{id}/ticks` date a step, order its ticks and name the run, and what do the
  lists and the quantiles return?
- **Decided:**
  - **Ticks.** One page of one path (`path` is required), ordered by `(step, symbol)` with the symbols in
    code-point order, as the replay feed orders its ticks; `seq` is 1, 2, 3 without gaps over the path. A run
    that has not completed answers 409 `run-not-complete`; an unknown run or a path past `n_paths` answers 404.
    A run kept in full is read from `path_value`; a run kept as quantiles is generated again from its seed, and
    only the shard that holds the path (250 paths) is generated. Both give the same text (tested for GBM, OU and
    Merton, across the shard joins).
  - **Dates.** Step 0 is the first NYSE session after the latest `window_end` of the run's calibrations (the day
    the start prices describe, or the last of them); each next step is the next session; `ts` is that session's
    close in UTC (DL-019). The calendar is extended to 2045 for long runs. `session` is the step from 0 and
    `session_date` is null, as the contract says for synthetic ticks.
  - **Fingerprint.** `xxh3:` and 32 hex digits over the generator version, the run id, model, seed, paths, steps,
    scenario, the stored correlation matrix (as stored, before repair) and each instrument's start price,
    parameters and fitting library version. The same on every page and every path of a run; another run, seed or
    parameter gives another value. `GENERATOR_VERSION` changes whenever the generators would give other prices
    for the same request.
  - **Lists.** `GET /runs` and `GET /calibrations` page by cursor in the market's envelope (`items`,
    `next_cursor`; `limit` default 500, at most 2000), newest first by `(created_at, id)`, so a page never repeats
    or skips a row that arrives meanwhile (Lane A's review of #80: adding paging later would break callers).
    `GET /runs` filters by `status` and `instrument`; its status is the one `GET /runs/{id}` shows (a run whose
    job the queue gave up on is `failed`), and a run not yet generated is found by instrument through its
    request. `GET /calibrations` lists the **stored fits** only, filtered by `instrument`, `model` and
    `converged`; a queued or refused calibration is read by its id.
  - **Quantiles.** `GET /runs/{id}/quantiles?instrument=` returns the stored per-step quantiles
    (0.01 to 0.99) for each instrument, with the start price; `step` k is tick `session` k - 1. The instrument
    filter exists because a long run holds up to 40 instruments of 2,520 steps.
- **Why:** the contract fixes the order, the gap-free `seq` and the timestamp rule; paging must exist from the
  first release; one shard per page keeps a quantiles-only run cheap to read (a page costs the same as a stored
  one, measured under 2 s).
- **Affects:** `reads.py`, `api_runs.py`, `api_calibrations.py`, `domain/calendar.py`; Lane A's synthetic
  adapter; the Results, Simulations and Create Portfolio pages (B20).
- **If changed:** the order or the fingerprint is part of the C1 contract: change it with Lane A.

### DL-043 Stress scenarios: what they change and how a stressed run is made

- **Asked:** what exactly do a price shock and a volatility multiplier do to a run, and what is a stressed run?
- **Decided:**
  - **Scenarios are rows** (`scenario`: `code`, `name`, `type`, `params`). Two types. They can be added with
    `POST /scenarios` (quants and admins) or inserted with SQL; no code changes. Two are seeded as examples
    (migration 0003): `flash_crash` (20% at step 21) and `vol_spike` (three times normal over steps 21 to 63).
  - **`price_shock`** `{drop, at_step, recovery_steps = 0}`: from step `at_step` every price of every instrument
    is multiplied by `1 - drop`. With `recovery_steps` above 0 the fall heals in a straight line and is gone at
    `at_step + recovery_steps`. Steps count from 1 (the first generated step, tick `session` 0).
  - **`vol_multiplier`** `{multiplier, from_step, to_step}`: the diffusion volatility is `multiplier` times its
    calibrated value over those steps, both included. It is applied inside the generators (an optional
    per-step scale), so the Ito correction of GBM and the noise of OU follow the stressed value; Merton's jumps are
    not scaled. Output with no scale is bit for bit what it was.
  - **A stressed run** is a derived run: the same model, seed, paths, steps, instruments, start prices, parameters
    and stored correlation as its parent, read from the parent, with the scenario on top. So it uses the parent's
    shocks and differs from it only by the stress, and nothing is read from the market. It has `parent_run_id`
    and `scenario`, its own statistics, quantiles, paths (by the storage rule) and median path, and its ticks
    carry `scenario`. The parent is never written to (tested byte for byte).
  - **Refusals:** a parameter out of its bounds is 422 naming the field (`errors: [{field, message}]`); a step
    beyond the run's length is 422 naming `at_step` or `to_step`; an unknown scenario or parent is 404; a parent
    that has not completed is 409; viewers and analysts are 403.
- **Why:** reusing the parent's shocks makes "what did the crash do" a clean difference; scaling sigma where it
  enters (not by multiplying shocks afterwards) keeps the stressed model a real GBM or OU with a larger sigma.
- **Affects:** `domain/scenarios.py`, the generators, `stress.py`, `api_scenarios.py`, `reads.py` (ticks and the
  fingerprint include the scenario), Lane A's stressed portfolio (demo step 4).
- **If changed:** a new type is a new `type` value, a Pydantic model, a CHECK in the database and an overlay
  function; the API and the tick feed do not change.
