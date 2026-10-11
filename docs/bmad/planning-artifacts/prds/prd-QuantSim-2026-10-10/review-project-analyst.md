# Review: project analyst (Omar), 2026-10-10

Assumptions:
- Mid-I falls around 2026-10-30, leaving about 14 working days.
- Git authors `Ali-Mazhar05` and `alimazhar` are the same person.

## Findings
| # | Severity | Finding | Fix |
|---|---|---|---|
| 1 | Critical | Members B and C have no Iteration 1 commits; every commit since September is by A. SM-6 and rubric criterion 6 fail, and A is the bottleneck. | B owns the I1-20 to I1-28 PRs and C owns I1-40 to I1-43. A reviews and does not write them. Each member merges at least 2 PRs a week. |
| 2 | Critical | The market path is about 25–30 person-days for B, with no buffer. | Apply the cut list below. Keep at least 3 days of buffer. |
| 3 | Critical | The build laptop's disk is full and Docker is down, which blocks every backend FR. | Free at least 20 GB, or switch the CI host with `host.sh`, within 1 day. |
| 4 | Critical | SM-4 needs 10 days of scheduled runs, but the scheduler is not built and there is no always-on host. | Reduce SM-4 to 3–5 days plus a manual run log, or provision Oracle by about 10-14. |
| 5 | High | The Mid-I date is unknown. | Ask the supervisor this week. |
| 6 | High | Six unmerged branches are piling up, and the stacked branches risk conflicts. | Merge in order: PR #12, `git-flow-skill`, `iteration-plan`, `centralized-jenkins`, `service-template`, `platform-service`. |
| 7 | High | The Oracle VM and DuckDNS name are not provisioned and have no task. | Add I1-03 (A, M size, by 10-16). Fall back to FR-11. |
| 8 | High | The Tiingo key is not in any secrets file, and the limits are unconfirmed. | Add an S task before I1-22 merges. |
| 9 | High | The untracked `admin_password` file and `ci/jenkins/.state/` could be committed by accident. | Add both to `.gitignore`; confirm the password is not in history. |
| 10 | High | Price precision is undecided and blocks the I1-20 migration. | Decide by 10-12; `NUMERIC(23,8)` is safer. |
| 11 | Medium | FR-21 is new scope with no task id. | Defer it, or add it as I1-31 (M). |
| 12 | Medium | I1-23 and I1-26 wording and the two D4 versions are still unedited. | Update them in the `iteration-plan` PR. |
| 13 | Medium | The I1-40 ERD depends on the merged schema. | Draft the ERD as soon as I1-20 merges. |
| 14 | Low | Open Questions 4, 5 and 7 are unresolved; 7 blocks I1-41. | Decide all three in one team call. |

## Cut list (cut in this order)
1. FR-21 symbol directory
2. FR-28 corporate actions
3. I1-17 tracing and I1-29 correlation
4. SM-8: backfill only 1–2 years, and drop the catch-up run and the backfill bound
5. FR-31: keep only logs and the health and ready endpoints
6. FR-12 backup and the FR-10 webhook
7. I1-45 admin page and the p95 measurement
8. Backend on ACC/PROD

Never cut: FR-23, FR-25, FR-26, I1-28, FR-16 and FR-30.

## Critical path
| Step | Task | Owner | Target |
|---|---|---|---|
| 0 | Free disk; update `.gitignore` | A | 10-11 |
| 1 | Merge PR #12, template, platform | A | 10-15 |
| 2 | I1-20 schema | B | 10-15 |
| 3 | Tiingo key; I1-22 adapter | B | 10-19 |
| 4 | I1-23 gate | B | 10-21 |
| 5 | I1-24 pipeline | B, with A pairing | 10-24 |
| 6 | I1-21, I1-26 lite, I1-27 | B, A | 10-26 |
| 7 | I1-28 planted-fault run on TEST | B | 10-27 |
| 8 | I1-42 and I1-43 frontend, I1-40 diagrams | C | 10-27 |
| 9 | I1-53 `v0.1.0` release | A | 10-28 |
| — | Buffer and rehearsal | All | 10-29 onward |
