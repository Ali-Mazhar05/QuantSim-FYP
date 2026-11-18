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
| DL-015 | Service tokens for the feeds | Open | Lane A |
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
  and counts per symbol. Raw prices are never substituted.
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
- **Status: Open.** `Principal` has no service kind today (`auth.py`).
- **Working assumption:** Lane B changes nothing in `libs/qs_template` (Lane A owns it, Plan section 2); the
  HTTP adapters wait for K3, and file adapters over the fixtures are used meanwhile (Plan, "what to do while
  waiting"). If K3 needs a market-side change, Lane A proposes it.

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

- **Asked:** the plan puts fixture-serving stubs on DEV by 25 Nov for Lane A's HTTP adapter.
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
