# Proposal

## Why

The sign-in page still falls back to demo mode when the backend is unreachable. In that mode anyone can pick a role and enter the app on mock data. New people also cannot get an account unless an admin creates it, and no email address in the system has ever been proven to belong to its user.

Iteration 1 needs real accounts end to end:
- people register;
- they prove they own the email address;
- they set and reset their own password;
- they are governed by their role, as the role-specific display (decision B) assumes.

## What Changes

- **New public sign-up:**
  - Fields: username, email, password and confirm password, plus an account type of Viewer, Analyst or Quant.
  - Admin cannot be chosen; only an existing admin can make someone an admin.
  - The account starts **unverified** and cannot sign in.
  - A single-use verification link is emailed. Opening it verifies the email and activates the account.
- **Approval for Quant and Analyst:**
  - A Viewer can sign in as soon as their email is verified.
  - A Quant or Analyst sign-up also waits for an admin. Until then the person sees a "Waiting for admin approval" screen.
  - On the Users page the admin can Approve (the user is emailed and can sign in) or Reject (the account is disabled).
  - Accounts an admin creates need no approval.
- **No account discovery through email:**
  - Sign-up, resend-verification and forgot-password always give the same "check your email" answer, whether or not the email is known.
  - If the email already has an account, that inbox gets a "you already have an account" email instead of a second account.
  - Only a taken *username* is reported, because usernames are visible inside the app.
- **Password reset:**
  - "Forgot password" emails a single-use set-password link.
  - Setting the password also verifies the email and ends every existing session of that account.
- **Admin invitations:**
  - An admin creates a user with username, email and role, and no password.
  - The user receives a set-password link that verifies the email.
  - The Users page shows such accounts as **Invited** until the link is used.
  - **BREAKING (API):** `POST /users` no longer accepts `password`. The first-admin CLI still sets one.
- **Email delivery:**
  - Mail is written to a mail outbox in the same transaction as the account change, so a rolled-back sign-up never sends mail.
  - The platform's existing background worker sends it over SMTP with retries.
  - DEV and TEST deliver to a local Mailpit inbox, so no real mail leaves the laptop. ACC and PROD send through Gmail SMTP.
  - The sender everywhere is `QuantSim <alimazhar+QuantSim@gmail.com>`. The Gmail account and app password are configured later by the user.
- **Abuse limits:**
  - Per client address on sign-up, resend and forgot-password.
  - At most 3 account emails per address per hour, so nobody can flood an inbox.
  - Unverified accounts are removed after 7 days, so they cannot hold a username or email for ever.
- **Test accounts:** a seed command creates four verified, approved accounts on DEV and TEST, one per role: `test.admin`, `test.quant`, `test.analyst` and `test.viewer`. Their passwords live in the encrypted secrets.
- **Sign-in:**
  - Works by username or email, with the same lockout rules for both.
  - A correct password on an unverified account says "verify your email first" and offers a resend.
- **Admin promote and demote:** the Users page gets a role control for users with `manage_roles`, using the existing `PUT /users/{id}/role`. The last-admin guard stays, and a role change ends that user's sessions.
- **BREAKING (frontend):**
  - Demo mode is removed. There is no "Demo as" sign-in and no mock-profile fallback.
  - An unreachable backend shows an error on the sign-in page.
  - Previewing a role from the top bar (equal or lower role) stays.
- **New screens in the POC style:** sign up, check your email, verify email, forgot password and set password. They reuse the sign-in card, inputs, role grid and button.

Requirements covered:

| Requirement | How this change covers it |
| --- | --- |
| FR-PLT-001 | Admin creates accounts by invitation. Self sign-up for non-admin accounts is an addition: the PDF lets an admin create accounts and does not forbid self sign-up |
| FR-PLT-002 | A password reset or role change ends existing sessions |
| FR-PLT-003 | Admin assigns and changes any role from the Users page |
| FR-PLT-004, FR-PLT-005 | Every page requires a real token from a verified account |
| FR-PLT-006 | Sign-up, verification, invitation, password set and role change are audited and published as `user.*` events |
| NFR-SEC-003 | The SMTP password is kept with the other secrets, in the SOPS files |
| NFR-SEC-004 | Only Argon2id password hashes and SHA-256 link-token hashes are stored |
| NFR-INT-002 | Role set and username format stay enforced by the database |
| NFR-REL-007 | Mail goes through a transactional outbox |

**Out of scope:**
- OAuth2 social sign-in, which is deferred until a fixed domain exists.
- Changing a verified email address.
- Two-factor sign-in.
- Per-row data entitlement, which comes with M3/M5 in Iteration 2.
- Making the API reachable from other computers. The deployed sites call the API on `localhost`, so only the machine running the environment can sign in today; this needs its own change once a fixed domain or named tunnel exists.

This change belongs to **Iteration 1** (tasks I1-16, I1-42 and I1-45 in `docs/iteration-plan.md`).

## Capabilities

### New Capabilities

- `account-access`: how a person gets an account and a session. Covers self sign-up (fields, account types, no account discovery, limits), sign-in by username or email, unverified-account handling, sign-out, and the web sign-in and sign-up pages with no demo fallback.
- `account-email`: the emailed links that prove email ownership and set passwords. Covers verification, resend, forgot and set password, admin invitations, link lifetime and single use, mail delivery through the outbox, per-environment mail transport, and removal of stale unverified accounts.
- `role-administration`: how an admin promotes and demotes users between Viewer, Analyst, Quant and Admin. Covers the guards (last admin, concurrent demotion), session cut-off and audit, and the Users-page control that only `manage_roles` holders see.

### Modified Capabilities

None. `openspec/specs/` has no capabilities yet.

## Impact

- **Platform service (`services/platform`):**
  - New public routes: `POST /auth/signup`, `POST /auth/verify-email`, `POST /auth/resend-verification`, `POST /auth/forgot-password` and `POST /auth/reset-password`.
  - `POST /users` becomes an invitation.
  - `LoginRequest` accepts an email.
  - `UserOut.status` becomes active, invited, pending or disabled.
  - New admin routes: `POST /users/{id}/approve`, `POST /users/{id}/reject` and `POST /users/{id}/resend-invite`.
  - **Migration `0003`:** `users.email_verified_at`, `approved_at` and `approved_by`, backfilled for existing accounts, plus the new tables `account_tokens` and `mail_outbox`.
  - The `relay` worker also sends mail.
  - New settings: `QS_SIGNUP_ENABLED`, `QS_PUBLIC_APP_URL`, `QS_SMTP_*`, and the limits.
- **Deploy:**
  - A Mailpit container on DEV and TEST (about 30 MB of memory).
  - SMTP settings in the ACC and PROD env files, with the password in `deploy/secrets/{acc,prod}.enc.env`.
- **Frontend (`frontend/`):**
  - `Login.tsx` changes.
  - New pages: `SignUp`, `CheckEmail`, `VerifyEmail`, `ForgotPassword` and `SetPassword`.
  - `services/api/platform.ts` gains the matching calls and `changeRole`.
  - `demo/demoState.ts` loses the mock `login(role)` path.
  - `Users.tsx` gains an invite form and a role control.
- **Docs:**
  - Decisions recorded in the iteration plan.
  - The auth section of `docs/QuantSim_Tech_Stack_and_Implementation.md` is updated.
  - `docs/ci-cd-team-guide.md` explains how to open Mailpit.
  - `docs/progress-log.md` is updated.
