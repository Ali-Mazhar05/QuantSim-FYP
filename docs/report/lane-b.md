# Lane B: Replay, Simulation and the Frontend Kit

Chapter, Iteration 2 (window 16 Nov to 23 Dec 2026). State of the code: `lane/b-simulation` after
the merges of 22 Nov 2026 (develop into the lane #155, B10 #78, B12 #177, B14 #179, B13 #180); the
calibration, Monte Carlo, read API, scenario and page branches are built and verified, in the merge
queue at the time of writing, and are marked **in review** below. Items that cannot be proved from a
developer machine are marked **partial** with the reason.

Lane B owns the replay of historical markets (module M2's feed and sessions), the stochastic
simulation service (calibration, Monte Carlo, stress scenarios), the frontend kit (typed client,
hooks, mock backend) and the pages built on it, and the Lane B part of the demo spine. This chapter
describes the design (section 1), the frontend kit (section 2), how the work is gated (section 3),
traces each Lane B requirement to the test that proves it (section 4), reports the results
(section 5), records the decisions (section 6) and lists what is not proved or not built
(section 7).

## 1. Design

### 1.1 A pull-based tick interface (ADR 01)

A consumer reads market data as a sequence of `market.tick.v1` ticks by `after_seq`, not as a push
stream. The same tick shape serves a historical replay (`GET /api/market/environments/{id}/ticks`)
and one path of a simulation (`GET /api/simulation/runs/{id}/ticks?path=`). Ticks are ordered by
`(session, symbol)` with a `seq` that starts at 1 and has no gaps; prices are decimal strings at the
database scale; replay ticks are adjusted prices (ADR 08) and a bar without an adjusted value refuses
the whole environment (422 `missing-adjusted-prices`, with the count per symbol). A page is 500 ticks
by default and at most 2,000, as in the rest of the market API.

The source fingerprint is `xxh3:` and 32 hex digits over the ordered served values (instrument,
session, revision and five adjusted values). It changes when a revision lands and when the vendor
restates an adjusted price without one. Activation freezes it (one row per environment); every page
carries the current one in `X-Source-Fingerprint`, so a consumer sees that data moved. The window is
read by session and a page reads only the sessions it covers, which keeps a page of a
40-instrument, 2,900-session window (116,000 bars) under 2 s at any position (DL-031).

### 1.2 The replay clock lives on the server (ADR 06, DL-032, DL-033)

A replay session stores an anchor (session index and server time), the speed (1, 5 or 20) and the state.
The position is computed on read: `min(anchor + floor(elapsed x speed), last)` while playing, so a
reload resumes at the server position, two readers see the same, and no background task runs. Play,
pause, speed and seek each write a new anchor. A session pins the fingerprint frozen at activation and
reports the current one. A live stream was the plan's first cut and is not built; the page polls
(DL-034).

### 1.3 A correlated synthetic market (ADR 02, ADR 03)

Paths come from exact discretisations: GBM and Ornstein-Uhlenbeck on log price are exact for any step,
Merton jump diffusion has a compensated drift. Shocks are correlated by a Cholesky factor of the
correlation matrix, repaired to the nearest valid matrix when it is not positive semi-definite, and
the repair is recorded. Paths are generated in fixed shards of 250 paths, each seeded only by
`(seed, shard)`, so a run's output does not depend on how many workers made it. A run stores its
statistics, per-step quantiles and, when paths x steps is at most 252,000 per instrument (and at most
10 instruments), every path value; larger runs keep the seed and the quantiles and **regenerate** a
path on demand, one shard per request, bit for bit equal to what the job generated (the matrix is
stored before repair so regeneration is exact, DL-039). The median path a portfolio binds to is the
lower median of the equal-weighted normalised terminal value, ties to the lowest index (DL-001).

### 1.4 Calibration and runs through ports (DL-035 to DL-041)

Calibration and Monte Carlo are jobs on the platform's queue (K1). The API answers 202 and the job
fetches prices through the service client (K3: service token, timeouts, retries, circuit breaker),
fits with `qs_quant.calibration` (K5) and refuses what the model refuses with its own reason; a run
needs a converged calibration of each of its instruments, and the database refuses a run on another
instrument's calibration (composite foreign key). Risk statistics use K6. A run's id is its job's id,
it is written in one transaction with its completion event, and a job killed mid-run leaves nothing.

### 1.5 Stress scenarios as data (DL-043)

A scenario is a row: a price shock (a fall at a step, with optional straight-line recovery) or a
volatility multiplier over a step range. The multiplier is applied inside the generators, per step, so
the Ito correction and the Ornstein-Uhlenbeck noise follow the stressed volatility; output without a
scale is unchanged. A stressed run is a derived run with the parent's seed, parameters, start prices
and stored correlation, so it differs from its parent only by the stress; the parent is never written
to. A new scenario of an existing type needs no code: it is a row, added with `POST /scenarios` or SQL.

### 1.6 The read API (DL-042)

Lists page by cursor in the market's envelope (`items`, `next_cursor`), newest first; a run's status
in the list is the one its detail shows. Quantiles are served per instrument. Synthetic ticks are dated
by the real NYSE closes after the day the start prices describe, and the fingerprint covers the run's
configuration, seed, parameters, stored correlation, scenario and generator version.

## 2. The frontend kit (K4, B02, B20)

The simulation, market and trading APIs export their OpenAPI documents (`scripts/export-openapi.py`);
`openapi-typescript` turns them into types (`npm run gen:api`). Three checks fail when an API and the
frontend disagree: each service's own test (the committed document is stale), `generated.test.ts`
(the committed types are stale) and `tsc` (a page uses a field that no longer exists). Hooks follow
one pattern (query keys per service, a classified error with a 403 state, one cache emptied on
sign-out and on a session that ends), and the mock backend (MSW) answers from fixtures typed against the
generated schema. Every Lane B page shows loading, data, empty, error and 403 states, never conveys
status by colour alone, and has stable test ids.

Pages on the kit: Market Data (interval selector, date range, metric cards, B02), Replay (server session,
play, pause, 1x, 5x, 20x, seek), Models (regime switching stays visible as Extended), Calibrations,
Simulations, Configure (fits each instrument, reuses a converged fit of the same window, refuses with the
model's reason), Run (polls the job), Results (fan chart from the stored quantiles, risk table, stressed
run beside the base, stress scenarios) and the run picker of Create Portfolio, which binds a portfolio at
the run's median path.

## 3. How the work is gated

Every pull request is built by Jenkins (a branch build and a merge build). Before a push the CI scripts
run on the developer machine in the pinned images: ruff, ruff format, mypy and the tests of each Python
project with a throwaway TimescaleDB, the migration check (upgrade, downgrade to base, upgrade) and the
frontend lint, type check, tests and build. The real-data tests need the recorded vendor corpus and are
skipped in CI (see section 7). The Playwright spine runs on TEST (`playwright-gate.sh test demo-spine`)
and gates test to acceptance.

## 4. Requirements traceability

Result: **pass** = proved by the named tests in CI; **in review** = the code and tests are built and
green in CI on their branch and wait for the lane merge; **partial** = something is not proved, see
section 7.

### 4.1 Functional requirements

| ID | Where | Proof | Result |
|---|---|---|---|
| B-FR-01 ordered gap-free ticks, byte-identical reads | B12 | `test_replay_feed`: ordering, `seq` 1..n, contract on every tick, paging equals one read at any size; the live feed equals the committed fixtures (1,265 ticks) | pass |
| B-FR-02 fingerprint changes only with data | B12 | `test_replay_feed`: a revision and a restated adjusted price change it; another instrument and a bar outside the window do not | pass |
| B-FR-03 hourly and tick cannot be replayed | B12 | `test_replay_feed`, `test_feed_contract_api`: 422 with a distinct type each | pass |
| B-FR-04 inverted window refused by API and database | B12 | creation 422; the `bar`/environment CHECK exists since Iteration 1 | pass |
| B-FR-05 lists for pickers | C2, B18 | environment filters `type`, `owner`; `GET /runs` and `/calibrations` with filters and paging (`test_reads`) | in review |
| B-FR-06 play, pause, speed, seek | B13 | `test_replay_sessions`: 5x for 2 s advances 10; pause freezes; seek then play; speed change re-anchors; analyst 403 | pass |
| B-FR-07 stream resumes after reconnect | B13 | cut by design (DL-034); polling resumes at the server position | partial (cut) |
| B-FR-08 calibrate, fit equals K5, fingerprint | B15 | `test_calibrations`, `test_calibrations_k5`: stored fit equals a direct K5 call; unchanged data reproduces the fingerprint | in review |
| B-FR-09 short history and refusals readable | B15 | 59 sessions gives 422 `insufficient_history`; OU on a random walk gives K5's `not_mean_reverting` | in review |
| B-FR-10 exact generators with correlated shocks | B10 | `test_gbm`, `test_ou`, `test_merton`, `test_sharding`: moments within 3 SE at 20,000 paths; shock correlation within 0.02; seed sweeps | pass |
| B-FR-11 reproducible from the seed, any worker count | B10, B16 | identical output with 1, 2 and 4 workers (real processes) | pass |
| B-FR-12 other instrument's calibration refused by the database | B14 | `test_schema`: raw insert fails with `run_instrument_calibration_same_instrument`; the valid pairing is accepted | pass |
| B-FR-13 run statistics, VaR <= CVaR equal K6 | B16 | `test_runs`, `test_run_adapters`: stored statistics; VaR and CVaR equal K6 and the specification formula | in review |
| B-FR-14 regenerated path equals the stored one | B16, B18 | `test_runs`, `test_reads`: GBM, OU and Merton across shard joins; stored and regenerated ticks equal | in review |
| B-FR-15 scenarios make derived runs, parent unchanged | B17 | `test_stress`: parent byte for byte; derived links to parent | in review |
| B-FR-16 a new scenario is a row | B17 | `test_stress`: a 90% crash inserted with SQL works end to end; bad parameters give 422 naming the field | in review |
| B-FR-17 seven pages on the typed client | B20 | page tests per state; Replay resumes at the server position | in review |
| B-FR-18 types from the APIs, drift fails CI | K4 | `test_openapi_export`, `generated.test.ts`, `tsc` (proved by renaming a market field: three failures) | pass |
| B-FR-19 pages run on mocks | K4 | page tests on MSW with no backend | pass |
| B-FR-20 interval selector and metric cards | B02 | `MarketData.controls.test` | pass (built; PR waits) |
| B-FR-21 the spine in Playwright on TEST | B22 | `lane-b-spine.spec.ts` type-checked and listed; not run | partial |

### 4.2 Non-functional requirements

| ID | Proof | Result |
|---|---|---|
| B-NFR-01 submit 202 under 800 ms p95 | 100 submits measured, p95 under 0.8 s (runs); calibration submit under 0.8 s | in review |
| B-NFR-02 pages under 2 s p95 | replay feed 40 x 2,900 first, middle and last page under 2 s (CI); synthetic tick pages, stored and regenerated, under 2 s | pass / in review |
| B-NFR-03 10,000 x 252 completes and is measured | the 1,000 x 252 demo run completes (about 75 s here, up to 150 s on a loaded host); the 10,000 x 252 run belongs to Lane C's study | partial |
| B-NFR-04 shards of 250, identical for 1, 2, 4 workers | `test_sharding` | pass |
| B-NFR-05 determinism | same seed identical, killed run rerun identical, replay reads byte-identical | pass |
| B-NFR-06 statistical validity | seed sweeps (a single fixed seed gave z = -3.4 on a correct generator, so no single-seed test is kept); a 3,000,000-path compensator test | pass |
| B-NFR-07 NUMERIC in the database, strings on the wire | test over every price and statistic column; the tick schema rejects JSON numbers | pass |
| B-NFR-08 constraints tested on real PostgreSQL | 55 refusals each naming its rule, plus the replay and activation tables | pass |
| B-NFR-09 duplicate submit returns the same run, event with state | idempotency tests; the completion event is written in the run's transaction | in review |
| B-NFR-10 timeout, retries, breaker on the price fetch | the K3 client carries them; failure handling tested on this side and the client's wiring on a mock transport | partial |
| B-NFR-11 role matrix | per route for market and simulation; a service token reads and cannot write | pass / in review |
| B-NFR-12 type check fails on drift; consumer tests run in the pipeline | the drift checks pass; the consumer tests of Lanes A and C are not in the pipeline yet | partial |
| B-NFR-13 progress events, duration, queue depth | `sim.progress` about every tenth, a structured line per run; the admin queue-depth route is not built | partial |
| B-NFR-14 memory limit, one thread per worker | `OMP_NUM_THREADS=1`, a shard pool of cores minus one, `max_run_values` caps a run; the compose limits are Lane A's file | partial |
| B-NFR-15 four states on every page, layout unchanged | page tests per state; prototype layout kept (ADR 06) | in review |
| B-NFR-16 three consecutive green spine runs | not possible before TEST has the services | not proved |

## 5. Test results

Counts are from CI runs of 22 Nov 2026 on the stacked branches.

| Level | Result |
|---|---|
| Market service (with B12, B13) | 481 passed in CI; with the recorded corpus added, 601 passed and none skipped (the 120 real-data tests included), run locally on the B16 tip on 22 Nov |
| Simulation service (with B10 to B17) | 417 passed |
| Frontend | 21 test files, all passing |
| Migrations | market 0001 to 0005 and simulation 0001 to 0003 apply from empty, reverse fully and apply again |
| Generators | 100% branch coverage of the generators (B10) |

The demo-size run (1,000 paths x 252 steps x 5 names, 1,260,000 stored values) takes about 75 s on the
development machine and up to 150 s on a loaded host. The cost is PostgreSQL checking the composite
foreign key of `path_value` row by row (13.6 s per 252,000 rows with the key, 2.0 s without). The key
stays (DL-041); a set-based check is the recorded alternative.

## 6. Decisions and design changes

ADRs 01 (pull-based tick interface), 02 (correlated synthetic market), 03 (path storage), 06
(prototype UI additions only) and 08 (adjusted prices) are Accepted; ADR 09 (service tokens) is Lane A's.
`docs/decision-log.md` holds DL-001 to DL-043 with the question, the decision and the reason. Changes
made while building, each with its reason there: the feed reads a large window by session and orders
symbols by code point (DL-031); activation is idempotent in effect and a ready environment is served
(contracts README); vol multipliers act inside the generators, not on shocks afterwards (DL-043); a
stressed run reads its inputs from its parent, nothing from the market (DL-043).

## 7. What is not proved or not built

- **The real-data market tests** need the recorded corpus and are skipped in CI; all 120 passed in a local run on the finished stack (601 of 601 market tests); they also ran on
  the B12 branch before the merges. CI itself still skips them.
- **The spine (B22)** is written and type-checked but has not run: TEST needs the simulation service, its
  market URL and service credentials in compose (Lane A's files), and the recorded data (Lane C).
- **B-FR-07** (live stream) was cut by design. **The admin queue-depth route** (B-NFR-13) and the
  **simulation ERD** are not built. The consumer contract tests of Lanes A and C are not in the pipeline.
- **B-NFR-03**: the 10,000 x 252 run is Lane C's performance study.
- Calibration reads prices when the job runs, not when it is submitted; a restatement between the two
  shows in the fingerprint.
- Regime switching has no generator or fit: it stays an Extended item on the Models page.
