# Iteration 1 audit against FYP Documentation (2)

**Source of truth:** `FYP_Documentation (2).pdf`, §3.4 (Iteration 1 plan), §4.3 (use cases), §4.4 (requirements), §4.5 (non-functional requirements), §6 (implementation and demonstration evidence), §7 (test cases).
**Declared deviations from it** (decided by the team, see section 5): Tiingo instead of yfinance, JWT access and refresh tokens instead of cookie sessions, Jenkins instead of GitHub Actions wording, and the prototype as the only UI definition.
**State audited:** `develop` at `f663694` on 2026-10-15, plus the open pull requests named in each row. Statuses change as the merge chain lands; update the table in the same pull request that changes them.

| Mark | Meaning |
|---|---|
| ✅ Done | On `develop` |
| 🟡 Built | Written and tested, on an open pull request that is not merged yet |
| ⚠ Partial | Some of the requirement is met; the gap is stated |
| ❌ Missing | Not built |

---

## 1. Requirements

### 1.1 Authentication (§4.4.1)

| ID | Requirement | State | Evidence and notes |
|---|---|---|---|
| FR-AUTH-01 | Register, normalised e-mail, reject duplicates | ✅ Done | Platform service sign-up with e-mail verification and admin approval (#47 to #51) |
| FR-AUTH-02 | Verify password hash, session only on success | ✅ Done | Sign-in issues a signed access token and a refresh token |
| FR-AUTH-03 | Hashed session identifier with expiry and revocation; logout revokes | ✅ Done | Refresh tokens are stored hashed with expiry and rotation. Logout and revocation: see TC-AUTH-03 below. *Deviation: JWT, not a cookie session* |
| FR-AUTH-04 | Reject unauthenticated or expired requests to protected endpoints | ✅ Done | Every market route declares its allowed roles; a route-by-role matrix test fails if one is missing |

### 1.2 Database (§4.4.2)

| ID | Requirement | State | Evidence and notes |
|---|---|---|---|
| FR-DB-01 | Repeatable initialisation or migrations for user, session, asset, run and observation records | ✅ Done | `services/market/migrations/versions/0001_market_schema.py`; platform migrations; the migration check (up, down, up) runs in Jenkins |
| FR-DB-02 | Foreign keys and required fields enforced | ✅ Done | Constraints in the migration; database tests refuse bad rows |
| FR-DB-03 | Key prevents duplicate bars per asset, timestamp and source | ⚠ Partial | The key is instrument plus session. The FYP also names the source; with one vendor this is equivalent. Record it as an exception in the report |
| FR-DB-04 | Daily bars are the source of truth, no weekly, monthly or yearly tables | ✅ Done | Only `bar` is stored; other intervals are derived |

### 1.3 Ingestion engine (§4.4.3)

| ID | Requirement | State | Evidence and notes |
|---|---|---|---|
| FR-ING-01 | Retrieve daily OHLCV for a symbol and range | 🟡 Built | Tiingo adapter #57, pipeline #58. *Deviation: Tiingo, not yfinance* |
| FR-ING-02 | Provider interval, adjustment, date bounds, timeout and timezone set explicitly | 🟡 Built | Explicit settings and the vendor section of `services/market/README.md`. The report must state the adjusted-price and session-date policy for Tiingo |
| FR-ING-03 | Validate and normalise, count and log rejected rows | ✅ Done | Cleaning gate, 55 tests, a property test that the report always adds up |
| FR-ING-04 | Idempotent upsert on the uniqueness constraint | 🟡 Built | Pipeline #58: same window twice adds nothing; a changed vendor value is a revision |
| FR-ING-05 | Run record: range, source, start and finish, status, counts, bounded failure summary | 🟡 Built | #58, #61. The requested range is null when the default window is used; it is recorded per item |
| FR-ING-06 | Operator-triggered or scheduled refresh, no real-time promise | 🟡 Built | Manual and backfill route (admin) and scheduler #61 |

### 1.4 Market data API and dashboard (§4.4.4)

| ID | Requirement | State | Evidence and notes |
|---|---|---|---|
| FR-MKT-01 | Ordered observations for a symbol and range, documented boundary convention | 🟡 Built | #62. Both ends inclusive, documented in the market README |
| FR-MKT-02 | Daily, weekly, monthly, yearly with first, max, min, last, sum | 🟡 Built | `GET /instruments/{id}/candles`, merged into #62 by #67. Checked against pandas |
| FR-MKT-03 | Empty range returns an empty success | 🟡 Built | Tested for every interval |
| FR-DASH-01 | POC charts request the series through the REST API | ⚠ Partial | Merged (#69), but the pages show an error message until the market service is deployed |
| FR-DASH-02 | Backend returns the metric set (return, volatility, drawdown) | 🟡 Built | `GET /instruments/{id}/metrics`, checked against numpy, split-adjusted. The prototype has no metrics control, so the UI does not show them (section 5) |

### 1.5 Non-functional requirements (§4.5)

| ID | Requirement | State | Evidence and notes |
|---|---|---|---|
| NFR-SEC-01 | Salted adaptive password hashing | ✅ Done | Platform service |
| NFR-SEC-02 | HttpOnly, SameSite cookies, CSRF approach | ⚠ Partial | *Deviation: tokens, not cookies.* The report must say how the tokens are stored and how CSRF is covered |
| NFR-SEC-03 | Secrets not in source control | ✅ Done | SOPS-encrypted per-environment files; the vendor key is stored the same way |
| NFR-SEC-04 | No account enumeration, no secrets in logs | ✅ Done | Same response for wrong password, unknown user and deactivated account; the vendor key is a secret string and is never logged |
| NFR-REL-01 | Provider failure recorded, process survives | 🟡 Built | Retry, backoff, circuit breaker, deferral |
| NFR-REL-02 | Repeating a request does not duplicate rows | 🟡 Built | #58 |
| NFR-REL-03 | Database failure is a controlled error, never reported as success | ⚠ Partial | A run is never marked successful, but after a database failure it stays `running` and the failure is only in the worker log. It is recovered and re-run later. No test yet |
| NFR-PERF-01 | Five years of one symbol under one second | 🟡 Built | Test in #67 loads about 1,250 rows and checks bars, candles and metrics |
| NFR-PERF-02 | Aggregation correct and chronological | 🟡 Built | Hand-computed unit tests plus pandas as the independent oracle |
| NFR-MNT-01 | Initialisation repeatable from version-controlled files | ✅ Done | Alembic revisions, no manual DDL |
| NFR-MNT-02 | Consistent API routes and fields | ⚠ Partial | Consistent by convention under `/api/market`; no contract test beyond the exported OpenAPI document |

---

## 2. Acceptance test cases (Table 9)

| Test | State | Evidence |
|---|---|---|
| TC-DB-01 clean initialisation | 🟡 Built | Migration check; schema tests |
| TC-DB-02 same bar twice | 🟡 Built | Pipeline database tests |
| TC-ING-01 valid ingest, queryable | 🟡 Built | Runner and read-API tests on recorded bars |
| TC-ING-02 empty provider result is no-data | 🟡 Built | `no_data` run item status |
| TC-ING-03 timeout or rate limit gives a controlled failure | 🟡 Built | Adapter tests: 429 with `Retry-After`, 500, timeout |
| TC-ING-04 malformed rows excluded, counts reconcile | 🟡 Built | Gate tests and the reconciliation property test |
| TC-ING-05 database unavailable, run not reported successful | ⚠ Partial | See NFR-REL-03 |
| TC-MKT-01 one symbol in a date range, ordered | 🟡 Built | Read-API tests |
| TC-MKT-02 aggregate a fixed sample to week, month, year | 🟡 Built | `tests/test_series.py`, `tests/test_intervals_api.py` |
| TC-MET-01 metrics match a hand-calculated oracle | 🟡 Built | Hand-computed values plus numpy |
| TC-AUTH-01 register valid and duplicate | ✅ Done | Platform tests |
| TC-AUTH-02 login with correct and incorrect password | ✅ Done | Platform tests |
| TC-AUTH-03 protected endpoint rejected after logout | ✅ Done | Marked done by the team on 2026-10-15; being handled by a teammate. Link the pull request here when it merges |
| TC-UI-01 chart with a valid and an empty response | ✅ Done | `frontend/src/market-data.test.tsx` (#69) |

No row above counts as **executed** for the report until a green Jenkins run of the merged code exists; the report's "Not run" cells stay until then.

---

## 3. Demonstration evidence (§6.9)

| Item | State | What is needed |
|---|---|---|
| Clean database initialisation and the resulting schema | 🟡 Built | Deploy the market service to DEV (#63) and capture the migration log and the ERD |
| A successful ingestion run for a US equity over a bounded range | 🟡 Built | A run on DEV with the real key on three symbols |
| Stored observations queried back and shown on the POC chart | 🟡 Built | The wired Market Data page against a deployed backend, with a screenshot |
| Daily, weekly, monthly and yearly filtering with the defined aggregation | ⚠ Partial | Available through the API only. Demonstrate through the API documentation page |
| The finalised metrics for the selected range | ⚠ Partial | Same: API only |
| Successful and unsuccessful login, a valid protected request, rejection after logout | ✅ Done | Sign-in is live; logout rejection per TC-AUTH-03 |
| One non-happy-path case (empty provider response, invalid range, duplicate ingestion, database unavailable) | ⚠ Partial | Each exists as a test. There is no scripted demo; the planted-fault dataset and script are not written |
| A successful current CI run with the exact configured jobs visible | ⚠ Partial | The market pull requests' merge builds are green; their branch statuses are stale from builds killed by a full disk |

---

## 4. The report document itself

These are gaps in `FYP_Documentation (2).pdf`, independent of the code.

| Section | Gap |
|---|---|
| §3.7, §6.5, §6.10, §8.1, §8.2, §9.7, §10 | Status tables still say database, ingestion, authentication and chart integration are "Not yet implemented" |
| §6.4, §6.6 | Implementation record and the per-feature evidence template (source path, contract, validation, tables, tests, pull request) are unfilled |
| §6.8 | Technology table still lists yfinance and cookie sessions; exact CI jobs and versions are "to be confirmed" |
| §6.9 | Screenshot placeholder, milestone dates `[Insert date]` |
| §7.3 | Every test case reads "Not run" |
| §7.4, §7.7, §7.8 | Test results, defects and corrective actions, current validation status are empty |
| Deviations | No section records the four deviations in section 5, with cause, impact and recovery as §3.8 requires |
| Table 5 | Says "GitHub Testing" for the pipeline; it is Jenkins |

---

## 5. Declared deviations from the FYP document

| FYP says | Built | Cause | Impact |
|---|---|---|---|
| yfinance (§1.8.4, §4.4.3, §6) | Tiingo end-of-day | Keyed API with documented limits and corporate-action data; one shared key | Free tier is non-commercial; 50 requests an hour shared by all environments; limits to be confirmed on the vendor site |
| Server-managed cookie sessions (NFR-SEC-02) | JWT access tokens (15 minutes) and rotating refresh tokens | Verified locally by every service without calling the platform; matches the multi-service design | Report must describe token storage and CSRF handling |
| GitHub Actions wording (Table 5) | Jenkins | The pipeline is Jenkins | Correct the wording; evidence is the Jenkins build history |
| Charts filtered by interval and date range with metrics (§3.4, UC-04, UC-05) | Interval candles and metrics are served by the API; the prototype pages have no controls for them | The prototype is the single source of truth for the UI; no screen, field or control is added | Demonstrate filtering and metrics through the API documentation page |

---

## 6. Merge order for the open pull requests

Merge each one only when its Jenkins build is green, then press **Update branch** on the next.

| Order | Pull request | Needs | Note |
|---|---|---|---|
| 0 | n/a | n/a | Free disk space on the CI host; add `MARKET_DB_PASSWORD` with `ci/scripts/set-secret.sh MARKET_DB_PASSWORD all` before #63 |
| 1 | #57 Tiingo adapter | nothing | |
| 2 | #58 pipeline, #59 instrument master | #57 | Either order |
| 3 | #61 run routes and scheduler | #58, #59 | |
| 4 | #62 read API with candles and metrics | #58, #59 | Expect a keep-both-sides conflict in `main.py` and `tests/test_instruments_api.py` |
| 5 | #63 deployment | #61 | Fix the ten wrong seed exchange labels in `services/market/src/qs_market/data/universe.py` before the first seed |
| 6 | #64 symbol directory, #65 correlation | #59 / #62 | Both beyond the FYP; optional |
| 7 | #60 end-to-end tests | all above | |
| any time | #56 PRD, #66 handoff, #52 tunnel restart, this audit | nothing | Documentation and tooling only |

---

## 7. What remains, in priority order

1. Merge the chain in section 6 and get a green Jenkins run on `develop`, then deploy to DEV.
2. Fix the seed exchange labels before the first seed.
3. Run a real ingestion on DEV (three symbols) and capture the evidence in section 3.
4. Write the planted-fault dataset and demo script so there is one scripted non-happy-path case.
5. NFR-REL-03 and TC-ING-05: record a failed run when the database fails, and add the test.
6. Update the report (section 4) and add the deviations section (section 5).
