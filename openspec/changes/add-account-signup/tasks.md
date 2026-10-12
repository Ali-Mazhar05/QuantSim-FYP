# Tasks

Every group is one pull request:

- on its own branch from `develop`;
- the Jenkins `pr-merge` and `branch` checks green before merge;
- one-line commit messages with no punctuation.

## 1. Spec (`feature/account-signup-spec`)

- [ ] 1.1 Merge this OpenSpec change and the spec tooling into `develop`.
  - Done when `openspec validate add-account-signup --strict` passes and the PR is green.

## 2. Schema (`feature/platform-email-schema`)

- [ ] 2.1 Add migration `0003_account_verification` (design D9):
  - `users.email_verified_at`, `approved_at` and `approved_by`, the timestamps backfilled to `created_at`;
  - a nullable `users.password_hash`;
  - the tables `account_tokens` and `mail_outbox`;
  - matching `models.py`;
  - a downgrade that refuses while users without a password exist.
  - Tests in `test_migrations.py`: upgrade → downgrade → upgrade; existing users can still sign in after the upgrade; the downgrade refusal.
  - Done when `migration-check.sh` and `python-ci.sh` are green.

## 3. Platform: accounts, email and approval (`feature/platform-account-email`)

- [ ] 3.1 Add the mail outbox, the templates (verify, already-have-account, invite, reset, approved) and the sender loop in the relay worker (D4). Add the SMTP settings with the `QS_EMAIL_REQUIRED` fail-fast check, and the sender `QuantSim <alimazhar+QuantSim@gmail.com>` (D5).
  - Tests: a rollback queues nothing; a sent row is marked; retry with backoff, then failed; no secrets in logs; fail-fast at startup.
  - Done when they pass.
- [ ] 3.2 Add sign-up, verify-email and resend (D1, D2, D3, D6), and the Redis limits (D7).
  - Tests: one per scenario in the sign-up, no-reveal, limits, links and verification requirements.
  - Done when they pass.
- [ ] 3.3 Change sign-in: username or email; then the `email-unverified` check; then the `approval-pending` check. Add `UserOut.status` with `pending`. Add approve and reject for `manage_users`.
  - Tests:
    - a Viewer signs in after verification;
    - a Quant or Analyst gets 403 `approval-pending` until approved;
    - approve queues the approval mail;
    - reject disables;
    - approving a non-pending account → 409;
    - the lockout and uniform-401 scenarios.
  - Done when they pass.
- [ ] 3.4 Add forgot and reset password, admin invitations with resend-invite, and the daily clean-up (D8).
  - Tests: one per scenario in the set-password, invitation, reset-email, mail-volume and expiry requirements.
  - Done when they pass.
- [ ] 3.5 Add the `seed-test-users` command (D10). Add Mailpit to compose for DEV and TEST. Add `QS_PUBLIC_APP_URL` and the SMTP settings to every env file, and `TEST_USERS_PASSWORD` to the DEV and TEST secrets. Run the seed in the DEV and TEST deploy.
  - Update the route-matrix test, the API docstring, the auth section of `docs/QuantSim_Tech_Stack_and_Implementation.md`, and the Mailpit section of `docs/ci-cd-team-guide.md`.
  - Done when `python-ci.sh` is green.
- [ ] 3.6 Add the role-change end-to-end test:
  - promote and demote, checking capabilities;
  - old tokens refused;
  - same role publishes nothing;
  - concurrent mutual demotion leaves one admin.
  - Done when it passes.
- [ ] 3.7 Merge, then verify on DEV:
  - the four test users sign in;
  - a sign-up mail shows in Mailpit;
  - verify → Viewer signs in;
  - a Quant sign-up gets 403 `approval-pending`, then test.admin approves, then the Quant signs in;
  - forgot password → the Mailpit link → the new password works.
  - Done when this is recorded in the PR.

## 4. Frontend: auth screens and admin controls (`feature/frontend-account-pages`)

- [ ] 4.1 Extract `AuthCard`, `AuthField`, `RoleGrid` and `PasswordPair` from `Login.tsx` (D11). Remove demo mode. Sign-in uses username or email, with the unreachable, unverified and approval-pending screens and the forgot and create-account links.
  - Tests in `auth.test.tsx`: each scenario of the "real accounts only" requirement and the waiting screen.
  - Done when `frontend-ci.sh` is green.
- [ ] 4.2 Add `/signup`, `/check-email`, `/verify-email`, `/forgot-password` and `/set-password` in the POC style. Each reads its token from the fragment and clears it.
  - Tests in `signup.test.tsx` and `email-links.test.tsx`: each web scenario in `account-access` and `account-email`.
  - Done when green.
- [ ] 4.3 On `Users.tsx`:
  - the invite form with a role including Admin;
  - the Pending badge, Approve and Reject, and the "N awaiting approval" header;
  - "Resend invite";
  - the Role select for `manage_roles`, confirming before demoting an Admin.
  - Tests: the scenarios in `role-administration` that concern the page.
  - Done when green.
- [ ] 4.4 Merge and verify on the develop site in the browser:
  - each test user sees only its role's pages;
  - sign up as a Viewer and as a Quant, using the Mailpit links;
  - the Quant sees the waiting screen until test.admin approves it on the Users page;
  - forgot password from the sign-in page leads to the change-password page;
  - test.admin promotes and demotes a user.
  - Done when this is confirmed with screenshots in the PR.

## 5. Docs and promotion

- [ ] 5.1 Record the decisions in `docs/iteration-plan.md`:
  - self sign-up with email verification, as an addition to FR-PLT-001;
  - admin approval for Quant and Analyst;
  - invitations replace admin-set passwords;
  - Mailpit on DEV and TEST, Gmail on ACC and PROD.
  - Update `docs/progress-log.md` for I1-42 and I1-45.
  - Done when merged green.
- [ ] 5.2 Promote `develop` → `test` through the pipeline and repeat the 4.4 checks on the test site.
  - Done when `quantsim/test-verified` is set.
- [ ] 5.3 Once the user has set the Gmail app password, add the ACC and PROD SMTP settings and the encrypted password. Promote to acceptance and check that a reset email reaches a real Gmail inbox.
  - Done when `acceptance-signoff` is requested from the user. PROD promotion is the user's call.

## 6. Completion (`feature/account-completion`)

- [ ] 6.1 Add `POST /auth/change-password` for signed-in users, which ends other sessions, returns a fresh one and emails a notice. Add the "approval needed" email to admins when a Quant or Analyst verifies.
  - Tests: change keeps this session and ends the others; a wrong current password → 400 and counted; anonymous → 401; only Quant and Analyst verifications email admins.
  - Done when `python-ci.sh` is green.
- [ ] 6.2 Add Settings → Security change-password form, and Deactivate and Reactivate on the Users page (none on your own row).
  - Tests: `account-settings.test.tsx` and the new `users.test.tsx` cases.
  - Done when `frontend-ci.sh` is green.
- [ ] 6.3 Deploy through DEV, TEST, ACC and PROD, and check every account flow on each site with real email.

## Workflow follow-up

- After the PROD release, archive with `openspec archive add-account-signup`.
