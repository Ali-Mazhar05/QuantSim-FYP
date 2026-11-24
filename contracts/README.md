# Contracts

What one lane gives another. Each contract is owned by its provider and approved by every consumer
before it merges. This folder holds the contracts of **Lane B** (replay and simulation); Lane A is the
consumer of C1, C2 and C3, Lane C of C3 and C4.

| ID | Contract | Provider | Consumers | Where |
|---|---|---|---|---|
| C1 | Tick event `market.tick.v1` | B | A | `events/market.tick.v1.schema.json`, `events/samples/` |
| C2 | Feed and list endpoints | B | A | OpenAPI of the `market` and `simulation` services (section 3) |
| C3 | Recorded fixtures | B | A, C | `fixtures/` (section 4) |
| C4 | `POST /api/market/correlations` | B | C | exists; frozen as it is |

**Change rule.** After the contract freeze a contract changes only by an additive pull request approved
by its provider and every consumer. Consumers ignore fields they do not know. A breaking change ships
as `v2` beside `v1` and never replaces it. The decisions behind these rules are in `docs/adr/` (ADR 01,
03 and 08) and, for the smaller choices with their reasons and what to update if one changes, in
`docs/decision-log.md`.

## 1. C1: `market.tick.v1`

One session of one instrument. A historical replay and a synthetic path produce the same shape; a
consumer tells them apart only by `env_type`.

| Field | Type | Rule |
|---|---|---|
| `env_id` | uuid | The environment (replay) or the run (synthetic) |
| `env_type` | `replay` or `synthetic` | A stored `historical_replay` environment is written `replay` |
| `source_fingerprint` | string | Identifies the exact data served (below) |
| `seq` | integer, at least 1 | 1, 2, 3 without gaps, per environment and path |
| `session` | integer, at least 0 | Index of the session among the sessions present; for synthetic, the step from 0 |
| `session_date` | date or null, optional | The trading date of a replay session; absent or null for synthetic |
| `ts` | UTC timestamp with `Z` | The session close; 21:00 or 20:00 UTC for NYSE, depending on daylight saving time |
| `instrument_id`, `symbol` | uuid, string | |
| `open`, `high`, `low`, `close`, `volume` | decimal strings | Adjusted; never a JSON number (below) |
| `path_index` | integer or null | Required for synthetic; null or absent for replay |
| `scenario` | string or null | The stress scenario of a synthetic run; null otherwise |

**Order.** Ticks are ordered by `(session, symbol)`. `seq` starts at 1 and has no gaps over the ticks
emitted. A symbol with no bar on a session has no tick on it (the other symbols still do), so the
engine must tolerate an absent symbol on a session. `session` is not disturbed by the gap.

**Decimals.** Prices and volumes are strings of digits with an optional fraction: no sign, no
exponent, no leading zeros (`"73.8782285800"`). They are written at the scale of the database column:
ten decimals for prices, eight for volume, so a value reads the same wherever it came from. Prices
are above zero and `high` is not below `low`; JSON Schema cannot say that, so
`services/market/tests/contract_support.py` checks it and this is the rule to copy.

**Prices are adjusted** for splits and dividends (ADR 08). A bar with a missing adjusted value cannot
be served: the environment is refused (422 `urn:quantsim:problem:missing-adjusted-prices`, section 3)
and raw prices are never substituted.

**The fingerprint** is `xxh3:` and 32 hex digits over the ordered served values of the instruments in
the window: instrument, session, revision, and the five adjusted values. It changes when a bar
revision lands, **and when the vendor restates an adjusted price in the window without a revision**,
which happens at every dividend or split. So a replay of an old window can change after a dividend,
and the fingerprint is how a consumer notices. For a synthetic run it identifies the run: its seed,
configuration and code. Compare the value you read with the one frozen at activation; what to do on a
difference is the consumer's decision.

**A synthetic step has one price**, so `open`, `high`, `low` and `close` are equal and `volume` is
`"0.00000000"`. A market order that fills at the next session's open therefore fills at the next
step's price.

**Validate** with `events/market.tick.v1.schema.json` (JSON Schema 2020-12, for example the Python
`jsonschema` package) plus the two rules above. `events/samples/valid/` must pass and
`events/samples/invalid/` must fail, each for the reason in its name; both are tested in CI.

## 2. Reading the feed

Consumers pull. They read a page, apply it, and ask for the next with the last `seq` they applied, so
a restart resumes where it stopped. Nothing is pushed.

## 3. C2: endpoints

All paths are behind the gateway. Errors are `application/problem+json` with `type`, `title`,
`status` and `detail`. **Today** the market routes are live: the environment list filters, the replay
feed and activation (B12). The three simulation routes answer **501**
(`type: urn:quantsim:problem:not-implemented`) until the Monte Carlo and read API tasks build them;
their paths, parameters, models and the other errors below are final and tested.

| Method and path | Who | Answers |
|---|---|---|
| `GET /api/market/environments?type=&owner=` | any signed-in role | Environments, newest first. `type`: `historical_replay` or `synthetic`. `owner`: the creator's user id. 422 for a bad value. Each carries `source_fingerprint`, `activated_at` and `activated_by`, null until activated, so a read-only caller can read the frozen fingerprint (also on `GET /api/market/environments/{id}`) |
| `GET /api/market/environments/{id}/ticks?after_seq=0&limit=500` | any signed-in role | A page of ticks; header `X-Source-Fingerprint`. `limit` 1 to 2000, default 500 |
| `POST /api/market/environments/{id}/activate` | quant, admin | Freezes the fingerprint: `{environment_id, status: "active", source_fingerprint, missing_session_count, activated_by, activated_at}` |
| `GET/POST /api/market/replay-sessions`, `GET /replay-sessions/{id}`, `POST /replay-sessions/{id}/control` | read: all roles; create and control: quant, admin | A server-side clock over an activated environment: `position` and `session_date` computed at `server_time`, `state`, `speed`, `finished`, the pinned and current fingerprints. Control body `{action: play|pause|speed|seek, speed?, index?}` (DL-032 to DL-034) |
| `POST /api/simulation/runs` | quant, admin | Queue a Monte Carlo run (`model`, `instruments` with a calibration each, `n_paths`, `n_steps`, `seed?`, `correlation_window?`); answers 202 with the run and a `Location`; `Idempotency-Key` returns the same run, 409 when the key was used for a different request; 422 for the limits and calibrations; 503 with no price or correlation source (DL-038 to DL-041) |
| `POST /api/simulation/calibrations` | quant, admin | Queue a calibration (`instrument_id`, `model`, `window_start`, `window_end`); answers 202 with the id and a `Location`; `Idempotency-Key` returns the same calibration; 501 for a model with no fitting code, 503 with no price source (DL-035 to DL-037) |
| `GET /api/simulation/calibrations/{id}` | any signed-in role | One answer from queued to stored: `status` queued, running, succeeded (`calibration`), refused (`refusal` with code and reason, 422 inside) or failed (`error`) |
| `GET /api/simulation/runs?status=&instrument=` | any signed-in role | Completed or other runs for a picker: id, status, model, sizes, symbols, `median_path_index`, `parent_run_id`, `scenario` |
| `GET /api/simulation/runs/{id}` | any signed-in role | The run with progress, seed, storage mode and per-instrument statistics |
| `GET /api/simulation/runs/{id}/ticks?path=&after_seq=0&limit=500` | any signed-in role | A page of one path's ticks, from the stored values or regenerated from the seed. `path` is required (0 to `n_paths - 1`); without it 422, outside the run 404 |

**A page** is `{"items": [tick, ...], "next_after_seq": 4 }`. `next_after_seq` is the `seq` of the last
tick when more follow and `null` on the last page. A cursor past the end gives an empty page.

```
GET /api/market/environments/6f1c2a4e-3b8d-4f7a-9c21-0a5e7d9b1c01/ticks?after_seq=0&limit=2
200   X-Source-Fingerprint: xxh3:3f9a1c0e5b7d2a48c6e10f93b5d7a2c1
{"items": [ {"seq": 1, "session": 0, "symbol": "AAPL", ...},
            {"seq": 2, "session": 0, "symbol": "KO", ...} ],
 "next_after_seq": 2}
```

**Errors.** 401 no or bad token. 403 the role may not (activation by an analyst or a viewer). 404 the
environment or run does not exist. 422 a bad parameter, or an environment that cannot be replayed:
`urn:quantsim:problem:unsupported-frequency` for an hourly or tick environment,
`urn:quantsim:problem:not-a-replay-environment` for a synthetic one,
`urn:quantsim:problem:environment-not-ready` for an environment some of whose instruments have no data
yet, and `urn:quantsim:problem:missing-adjusted-prices` (with `missing`: bars per symbol) when a bar has
no adjusted value. 404 also for a `path` the run does not have (`path >= n_paths`):
`urn:quantsim:problem:not-found`, as for an unknown run. 501 on the simulation routes until they are built.

**Activation** moves a ready environment to `active` and freezes the fingerprint; doing it again after
the data moved freezes the new value, and the environment keeps one frozen value. Reading ticks needs a
ready or active environment; every page is served from one database snapshot, so its fingerprint always
describes the rows on it.

**Activating twice.** It is idempotent in effect: the second call answers 200 with the same body when the
data has not moved, and re-freezes the new fingerprint (a new `activated_at`) when it has. There is still
one frozen value per environment.

**Ticks of an environment that is not active.** A `ready` environment (never activated) is served: the
`X-Source-Fingerprint` header carries the live fingerprint and there is no frozen value to compare with
(`source_fingerprint` is null on the environment). A `draft` one answers 422
`environment-not-ready`. There is no 409: no state of the environment makes a read conflict with
anything. A consumer that needs the frozen value activates first.

```
POST /api/market/environments/6f1c2a4e-3b8d-4f7a-9c21-0a5e7d9b1c01/activate
422   Content-Type: application/problem+json
{"type": "urn:quantsim:problem:missing-adjusted-prices", "title": "Missing adjusted prices",
 "status": 422, "detail": "bars without adjusted prices: AAPL (3), KO (1)",
 "missing": {"AAPL": 3, "KO": 1}}
```

**Which environment is served.** A completed simulation run is an environment by identity: its ticks
carry `env_type: "synthetic"` and `env_id` equal to the run id, and a path is chosen with `?path=`. A
portfolio binds to the run's `median_path_index`: paths are ranked by the terminal value of the
equal-weighted basket of normalised prices and the lower median is taken, ties to the lowest index
(ADR 03).

## 4. C3: fixtures

Recorded, never edited by hand. Each file has a `meta` block that says how it was made; consumers
ignore it. They are valid examples of the contracts, so a file adapter can read them and an HTTP
adapter can be tested against the same shapes.

| File | What |
|---|---|
| `fixtures/replay_ticks_2020.json` | The replay feed for AAPL, MSFT, NVDA, TSLA and KO over every 2020 session: 1,265 ticks, one page (`items`, `next_after_seq: null`), with the `environment` (ids, symbols, window, fingerprint) |
| `fixtures/synthetic_ticks.json` | A synthetic run of three correlated GBM paths over AAPL, MSFT and NVDA, 60 steps from 2021-01-04: `run` and `paths[].items`. **Illustrative**, seeded (42), not a recorded run |
| `fixtures/correlation_rolling_60_5.json` | The real answer of `POST /api/market/correlations` for a rolling window of 60 sessions every 5, 2019 to 2021, over six recorded names (the recorded corpus holds six; the 40-name universe replaces it once loaded) |

**How they are made.** The recorded Tiingo corpus is ingested through the real pipeline into a real
database, with fixed instrument and environment ids, and the replay ticks are built by the function the
feed endpoint will use (`qs_market.feeds`), so a fixture and the service cannot disagree.

```
QS_REALDATA_DIR=<recorded corpus>  TEST_DATABASE_URL=<postgres>  \
  uv run --frozen --all-packages python scripts/make-fixtures.py            # write
  uv run --frozen --all-packages python scripts/make-fixtures.py --check    # fail if stale
```

The corpus is never committed and the Tiingo key is never used. `services/market/tests/test_fixtures.py`
checks the committed files in CI.
