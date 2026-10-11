# Review: business analyst (Nadia), 2026-10-10

## Critical
1. FR-21: no Symbol directory exists on a fresh deploy. Refuse with HTTP 503 `directory_unavailable` (override allowed); warn `stale_directory` when the copy is older than 3 days; add a metric for directory age.
2. FR-14: no bootstrap admin on a fresh deploy. Create the first admin from the SOPS secret and force a password change at first sign-in. Add the stray `admin_password` file to `.gitignore`.
3. FR-8/FR-24: DEV and TEST schedulers each get a 45/hour budget, up to 90 combined on one Tiingo key whose limit is 50/hour. Share one budget per API key, or disable the DEV scheduler.

## High
4. Wrong-role 403s are missing: triggering a run (quant, analyst, viewer); creating a replay session (analyst, viewer); user management and audit reads (non-admin). Add a role-by-route matrix test.
5. FR-15: no refresh or logout, so a 15-minute token expires mid-demo. Add refresh and logout, or make them an explicit non-goal.
6. FR-23: two different runs overlapping on the same Instrument and window. Return 409 with the active run id, or serialize runs per Instrument.
7. FR-22/24: a backfill can exhaust the daily run's budget. Reserve 40 requests a day for daily and catch-up runs.
8. FR-24: HTTP 401 from the Vendor (bad key) should fail the whole run as `vendor_auth`. State whether unknown symbols count toward the circuit breaker. Make repeated deferral visible.
9. SM-2/UJ-1: planted-fault run on TEST. Specify a fixture-vendor setting plus dedicated planted Instruments, excluded from SM-4 and the data-quality totals.
10. FR-29: no provenance. Return `run_id`, `vendor` and `ruleset_version` on each Bar and Revision.
11. SM-4: the wording reads as if it requires a partial day; it also assumes an always-on host. Change to "≥9 of 10 succeeded, none missing" and name the host.

## Medium
12. FR-25: gaps at close + 1 h produce false gaps daily because Tiingo data lands later. Use close + 6 h, or let the catch-up run judge gaps.
13. FR-27: the annualisation factor, sample vs population deviation and dividend-adjustment method are not stated. The 10-significant-digit check conflicts with NUMERIC(20,6).
14. FR-23/25: undefined what happens when a vendor correction fails the gate. Keep the published Bar, record a Rejected bar, raise no Revision.
15. FR-20: re-adding a retired symbol is undefined, as is a ticker reused by a new company.
16. FR-21: an admin-supplied exchange can conflict with the directory; a failed directory refresh has no metric.
17. FR-30: speed bounds are unclear (is 0 allowed?); must Instruments be active or have Bars in the window? FR-MKT-009 coverage is partial.
18. FR-22: undefined how a weekend run with zero Sessions ends, and which timezone "today" uses.
19. FR-PLT ids are mapped as groups; map each id to a named consequence.
20. Cloudflare R2 needs a card on file; tag it as an assumption.
21. TC-02 mapping is inconsistent between the PRD and addendum §A and §F.

## Low
22. Rename the glossary term "Approver" to "Pipeline approver".
23. Explain why FR-1 says 15 min and SM-5 says 10 min.
24. FR-29's 800 ms target needs a sample size and load.
25. Currency values are undefined.
26. The "Reproducible" NFR has no testable consequence.

## Open questions
- May three students share one Tiingo key on a server?
- Do FR-PLT-005/008 include scope grants or an audit index?
- Is Tiingo's EOD data available by 22:30 UTC?
- Which host runs scheduled ingestion for SM-4?
- May planted-fault data live in the TEST database?
- Are refresh and logout a non-goal?
- What status does a run with zero new Sessions get?
