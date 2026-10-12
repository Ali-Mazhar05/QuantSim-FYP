# Design

## Context

The motivation is in proposal.md (Why). The platform service already has these pieces:

- an Argon2id-hashed `users` table with case-insensitive unique indexes on username and email, and database checks on role and username format;
- login with lockout;
- rotating refresh tokens;
- the Redis token-revocation store;
- `PUT /users/{id}/role` with the last-admin lock and session cut-off;
- the audit trigger on `users`;
- `user.*` events through the transactional outbox, published by the `platform-relay` worker.

Requests reach the platform through each environment's Traefik gateway. Today the deployed sites call the API on `localhost:8081-8084`, so every browser that can reach it is on the Jenkins laptop. The frontend's demo fallback is in `Login.tsx`.

## Goals / Non-Goals

**Goals:**
- Prove email ownership before any self-created account can sign in.
- Give nobody a way to learn whether an email is registered without access to that inbox.
- Send mail only for committed changes, and never lose it.
- DEV and TEST send no real email.
- Stay free and self-hosted.

**Non-Goals:**
- Account approval queues: a verified sign-up is active, as the user decided.
- CAPTCHA, or any other paid or third-party anti-abuse service.
- HTML email design beyond a plain branded template.
- Changing an email address after verification.

## Decisions

### D1. Unverified accounts are real `users` rows with `email_verified_at IS NULL`

Sign-up inserts the user through the same `create_user` path as an admin invitation, with `email_verified_at` NULL.

Sign-in checks the password first, then verification:
- a correct password on an unverified account gives 403 `email-unverified`;
- a wrong password gives the ordinary 401 and counts toward lockout.

`UserOut.status` becomes:
- `disabled` when not active;
- `invited` when not verified;
- `pending` when verified but not approved;
- `active` otherwise.

The first three are the POC's states; `pending` is new and uses the POC's warning badge.

**Approval:** `approved_at` and `approved_by` are set at creation for Viewer sign-ups and for every admin-created account. They stay NULL for self sign-ups as Quant or Analyst.

Sign-in checks, in this order:
1. password;
2. active;
3. verified, otherwise 403 `email-unverified`;
4. approved, otherwise 403 `approval-pending`.

Approve and reject are `manage_users` actions. Approve sets the two columns and queues an approval email. Reject deactivates the account, which reuses the existing deactivate path, so the history and the last-admin rules stay as they are.

*Alternative:* sign up as Viewer and let the admin promote. Rejected because the person asked for Quant and the admin would have to remember that.

*Alternative:* a separate `signup_requests` table that becomes a user on verification. Rejected because two pending sign-ups could claim the same username and only fail when one is verified, and because it duplicates validation and audit.

### D2. One `account_tokens` table for every emailed link

Columns:
- `id`, `user_id`
- `purpose`, one of `verify_email`, `set_password` or `reset_password`
- `token_hash`: SHA-256, with a unique index
- `created_at`, `expires_at`, `used_at`

How the tokens are handled:
- **Issue:** a token comes from `secrets.token_urlsafe(32)`. Issuing marks earlier unused tokens of the same user and purpose as used, which voids them.
- **Use:** the row is selected `FOR UPDATE`, then checked for purpose, expiry and `used_at IS NULL`. It is marked used in the same transaction as its effect.
- **Errors:** every failure returns the same 400, so no reason is leaked.
- **Audit:** the table is not audited, like `refresh_tokens`. The user-level changes it causes are audited on `users`.

### D3. Links carry the token in the fragment and the page POSTs it

The link format is `{QS_PUBLIC_APP_URL}/verify-email#token=…` and `/set-password#token=…&purpose=reset|invite`.
- The fragment never reaches a server, a proxy log or a `Referer`.
- The page reads it, removes it from the address bar with `history.replaceState`, and POSTs it to the API.
- Verification is a POST, not a GET. Mail scanners that pre-open links, but do not run scripts, therefore cannot use it up.
- Verifying does not sign the person in. The page offers "Sign in", so that holding a link alone never yields a session.

### D4. Mail outbox plus a sender in the relay worker

`mail_outbox` holds:
- `id`, `to_address`, `template`, `params` (JSONB, with no secrets except the link)
- `created_at`, `attempts`, `next_attempt_at`, `sent_at`, `failed_at`, `last_error`

The service writes a row inside the request transaction, exactly like `add_event`. The existing `platform-relay` process gains a second loop:
1. It claims due rows with `FOR UPDATE SKIP LOCKED`.
2. It renders the template (plain text plus simple HTML, no external assets).
3. It sends through `aiosmtplib`, using STARTTLS or TLS per settings.
4. It backs off exponentially: 30 s, doubling, capped at 1 h, for up to 24 h.

Rows older than 7 days are deleted after sending, because they contain links.

*Alternative:* sending inside the request. Rejected because a slow or broken SMTP server would then fail sign-up, and a rolled-back transaction could still send mail. Another alternative, a Redpanda consumer, was rejected because it adds a hop and another container for no gain.

### D5. Mail transport per environment

- **DEV and TEST:**
  - A `mailpit` service (axllent/mailpit, MIT licence, pinned digest) joins the compose project on the backend network, with a 64 MB memory limit.
  - Its web inbox is published on the host only: `127.0.0.1:8025` for DEV and `:8026` for TEST.
  - The platform sends to `mailpit:1025` without auth. Nothing leaves the laptop.
- **ACC and PROD:** Gmail SMTP, as the user chose.
  - `smtp.gmail.com:587` with STARTTLS.
  - `QS_SMTP_USERNAME` is the Gmail account; `QS_SMTP_PASSWORD` is its app password, kept in the SOPS secrets.
  - Gmail allows about 500 messages a day.
- **Sender:** `QS_SMTP_FROM=QuantSim <alimazhar+QuantSim@gmail.com>` everywhere. Gmail accepts a `+` alias of the signed-in account as the From address.
- **Fail fast:** the platform refuses to start when `QS_EMAIL_REQUIRED=true` (ACC and PROD) and the SMTP host or password is missing.

### D6. Responses that reveal nothing

- **Sign-up:**
  1. Validate the body (422).
  2. Check the rate limit (429).
  3. Check the username; a taken username gives 409, because usernames are visible in-app.
  4. Then look up the email:
     - new email: create the account and queue a verify mail;
     - unverified account: queue a fresh verify mail;
     - verified account: queue an "already have an account" mail.
  5. Answer 202 in every case of step 4.

  All branches do the same Argon2 hashing of the submitted password, so response time does not reveal the branch.
- **Resend and forgot password:** always 202, with the hashing spent the same way.

### D7. Limits in Redis, fail closed

Both limits are fixed windows in Redis: `INCR` with `EXPIRE` on the first hit.

- **Per client** (`QS_SIGNUP_RATE_LIMIT`, default 10 per 3600 s): counts sign-up, resend and forgot-password attempts.
  - The address is the last entry of `X-Forwarded-For` as set by this environment's Traefik gateway; `request.client.host` is used when there is no gateway.
  - A caller can prepend fake entries but cannot change the last one, which Traefik appends.
- **Per email address:** 3 mails per hour, counted when a mail is queued. Over the limit, nothing is queued and the answer is unchanged.

If Redis is down, these routes return 503. Sign-in does not use these counters.

### D8. Daily clean-up of abandoned sign-ups

The relay worker runs a daily job. It deletes users who meet all of these:
- `email_verified_at IS NULL`;
- `created_by = id` (a self sign-up);
- `created_at` more than 7 days ago;
- they never had a session.

It sets the audit actor to a system id and publishes `user.expired`. Invitations have `created_by` set to the admin, so they are never matched.

### D9. Schema migration `0003_email_verification`

- **`users.email_verified_at`, `approved_at`** (timestamptz) and **`approved_by`** (uuid): `email_verified_at` and `approved_at` are backfilled to `created_at` for every existing row. The bootstrap admin and existing accounts were created by trusted operators.
- **`users.password_hash`:** becomes nullable, because an invited user has no password until the link is used. `verify_password(None, …)` already returns false.
- **New tables:** `account_tokens` and `mail_outbox`, with their indexes.

The downgrade drops the tables and the column. It refuses if any user has a NULL password hash, rather than inventing one.

### D10. Test accounts

A `platform seed-test-users` CLI command creates or updates `test.admin`, `test.quant`, `test.analyst` and `test.viewer`:
- They are verified and approved.
- Their emails are `alimazhar+qs-<role>@gmail.com`, so any mail lands in the user's own inbox.
- The passwords come from `TEST_USERS_PASSWORD` in the DEV and TEST encrypted secrets.

The DEV and TEST deploy runs the command after migrating. ACC and PROD never run it.

### D11. Frontend

- **Removed:**
  - The demo fallback, `login(role)` and `mode: 'demo'`.
  - The "Demo as" grid.
- **Shared pieces:**
  - `AuthCard`, `AuthField`, `RoleGrid` and `PasswordPair` are pulled out of `Login.tsx`.
  - Every auth screen is built from them, so they match the POC sign-in exactly.
- **New routes:** `/signup`, `/check-email`, `/verify-email`, `/forgot-password` and `/set-password`. They are public and redirect a signed-in visitor to `/dashboard`.
- **Users page:**
  - The admin "Add user" form drops the password field and gains a role select that includes Admin.
  - Invited rows get "Resend invite".
  - The Role column becomes a select for `useCan('manage_roles')`, with confirmation before demoting an Admin.
  - Rows update only from the platform's response.
- **Top bar:** the role preview stays and only narrows what is shown.

## Risks / Trade-offs

- **[Only the laptop running an environment can reach its API, because the sites call `localhost`.]** Verification links work for anyone on that laptop, but people on other machines cannot use the app at all yet. → This is out of scope here. It is listed in the proposal as the next infrastructure change: a named tunnel or fixed domain.
- **[A Gmail sending account can be rate-limited or flagged by Google.]** → The outbox retries for 24 hours. Brevo works the same way, and switching is a settings change.
- **[Emails may land in spam without a domain of our own (no SPF or DKIM for pages.dev).]** → The check-email screen says to look in spam. A custom domain fixes this later.
- **[A taken username is revealed by 409.]** → This is accepted, because usernames are visible to every signed-in user. The rate limit bounds probing.
- **[Sign-up spam can create unverified rows.]** → The per-client limit, the 7-day expiry and the per-address mail cap bound it. Unverified rows cannot sign in.
- **[A nullable `password_hash` loosens a column.]** → It is NULL only for invitations. A test asserts that sign-in with any password fails for those accounts.
- **[Removing demo mode makes the deployed site unusable without a running backend.]** → This is intended. The sign-in page states the problem, and the team guide explains how to start an environment.

## Migration Plan

1. Migration `0003` ships in its own PR with `migration-check.sh` (upgrade, downgrade and upgrade again on a scratch database). Existing users stay able to sign in, because of the backfill.
2. The platform PRs follow in order:
   - links, outbox and sender, plus Mailpit on DEV and TEST;
   - sign-up, resend and verify;
   - forgot and set password;
   - invitations.

   Each stays backward compatible with the current frontend, except that `POST /users` loses `password`. The current frontend does not call it.
3. ACC and PROD get their SMTP settings and secrets before the release that reaches them. Startup fails fast otherwise.
4. The frontend PRs follow the API they need.
5. **Rollback:**
   - Revert the frontend PRs.
   - Close sign-up with `QS_SIGNUP_ENABLED=false`.
   - The migration downgrade is available while no invited user without a password exists.

## Open Questions

- The Gmail account and app password for ACC and PROD. The user sets these later; they are settings only and are needed before the ACC promotion, not before DEV.
- Whether PROD keeps self sign-up on after the FYP-1 demo. This is a one-line env change.
