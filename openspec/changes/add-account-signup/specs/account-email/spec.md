# Spec Delta

## Purpose

The emailed links that prove a person owns their email address and let them set a password. Covers email verification, admin invitations, forgot and set password, link lifetime and single use, reliable delivery, the per-environment mail transport, and clean-up of accounts that never verify (FR-PLT-001, FR-PLT-002, FR-PLT-006, NFR-SEC-003, NFR-SEC-004, NFR-REL-007).

## ADDED Requirements

### Requirement: Account links are single-use, expiring and stored only as hashes

Every emailed link SHALL carry a random token of at least 256 bits, for one purpose and one account:
- verify email: valid 24 hours;
- set password after an invitation: valid 72 hours;
- reset password: valid 1 hour.

The platform SHALL store only a SHA-256 hash of the token (NFR-SEC-004). A token SHALL work once. Issuing a new token for the same account and purpose SHALL void the older ones. The token SHALL travel in the link's `#` fragment, so web servers and referrers never log it.

#### Scenario: A link works once

- **GIVEN** an unused verification link for `sara.k`
- **WHEN** it is used, and then used again
- **THEN** the first use succeeds and the second gets 400 "This link is invalid or has expired."

#### Scenario: An expired link

- **GIVEN** a reset link issued 61 minutes ago
- **WHEN** it is used
- **THEN** the response is 400 "This link is invalid or has expired." and the password is unchanged

#### Scenario: A newer link voids the older one

- **GIVEN** two verification links were sent to `sara.k`, one after the other
- **WHEN** the first link is used
- **THEN** it is refused with 400, and the second link still works

#### Scenario: A link for one purpose cannot be used for another

- **WHEN** a verification token is sent to the reset-password route
- **THEN** the response is 400 and nothing changes

### Requirement: Verifying the email activates a self sign-up

Using a valid verification link SHALL record the time the email was verified, after which the account can sign in. The change SHALL be audited and published as `user.email_verified`. The web page SHALL then show "Email verified" with a sign-in button; it does not sign the person in by itself.

#### Scenario: Verify then sign in

- **GIVEN** an unverified account `sara.k` with password P
- **WHEN** the verification link is opened in the browser
- **THEN** `/verify-email` shows "Email verified" and a "Sign in" button
- **AND** `sara.k`'s status becomes `active`
- **AND** signing in with P returns a token pair

#### Scenario: Opening a broken link

- **WHEN** `/verify-email` is opened with a missing, altered or used token
- **THEN** the page shows "This link is invalid or has expired." with a form to send a new link

### Requirement: Resend and forgot-password never reveal an account

`resend-verification` and `forgot-password` SHALL both take an email and always answer 202 "If an account uses that email, we have sent a link." They SHALL send mail only in these cases:
- **Resend:** the account exists and is unverified, in which case it sends a verification link.
- **Forgot password:** the account exists and is active, in which case it sends a reset link.

Unknown emails, verified emails on resend, and deactivated accounts SHALL get the same answer with no mail.

#### Scenario: Forgot password for a known and an unknown email

- **WHEN** forgot-password is sent for `sara@example.com` (an active account) and for `nobody@example.com`
- **THEN** both responses are the same 202
- **AND** only `sara@example.com` gets a reset email

#### Scenario: Resend for a verified account

- **GIVEN** `sara.k` is already verified
- **WHEN** resend-verification is sent for her email
- **THEN** the response is 202 and no email is sent

### Requirement: Setting a password through a link

Using a valid set-password link (from an invitation or a reset) with a new password of 12-1024 characters SHALL do all of the following:
- replace the Argon2id hash;
- mark the email verified;
- clear failed sign-ins and any lock;
- end every existing session of the account (FR-PLT-002);
- audit the change and publish `user.password_set`.

The web page SHALL ask for the password twice and then show a "Sign in" button.

#### Scenario: Reset ends old sessions

- **GIVEN** `sara.k` is signed in on two browsers and asks for a reset
- **WHEN** the reset link is used with a new password
- **THEN** both old refresh tokens are refused with 401
- **AND** the old access tokens are refused within the token-check window
- **AND** signing in with the new password works and the old one fails

#### Scenario: Reset unlocks a locked account

- **GIVEN** `sara.k` is locked after too many wrong passwords
- **WHEN** she sets a new password through a reset link
- **THEN** she can sign in with it at once

#### Scenario: Too-short password on the set-password page

- **WHEN** an 11-character password is entered on `/set-password`
- **THEN** the page shows the rule and nothing is sent
- **AND** if the platform still receives one, it answers 422 and leaves the link unused

### Requirement: Admins invite users instead of choosing their password

When an admin creates a user (`manage_users`), they SHALL give a username, an email, a display name and any role, including Admin, and no password. The platform SHALL create the account unverified with no usable password and email a set-password link valid for 72 hours. The Users page SHALL show the account as Invited and offer "Resend invite" until the link is used. The first-admin CLI SHALL keep setting a password directly and mark that account verified.

#### Scenario: Admin invites an analyst

- **GIVEN** an admin
- **WHEN** they create user `omar` with email `omar@example.com` and role `analyst`
- **THEN** the response is 201 with status `invited`
- **AND** a set-password email to `omar@example.com` is queued
- **AND** `omar` cannot sign in with any password until the link is used

#### Scenario: Admin resends an invite

- **GIVEN** `omar` is invited and his first link has expired
- **WHEN** the admin presses "Resend invite"
- **THEN** a new 72-hour link is queued and the old one stays void

#### Scenario: Invite with a taken email

- **WHEN** an admin invites a user with an email that already has an account
- **THEN** the response is 409 "That username or email is already in use."
- **AND** the admin is allowed to know this, because they hold `manage_users`

### Requirement: Account emails are delivered reliably and only for committed changes

Every account email SHALL be written to a mail outbox in the same database transaction as the change that causes it (NFR-REL-007). A background worker SHALL send pending mail over SMTP. On failure it SHALL retry with growing delays for up to 24 hours, then mark the mail failed and log it. The worker SHALL never write a token or password to the logs.

#### Scenario: A rolled-back sign-up sends nothing

- **GIVEN** a sign-up whose transaction fails after the account insert
- **WHEN** the transaction rolls back
- **THEN** no email is queued or sent

#### Scenario: The mail server is down for a while

- **GIVEN** the SMTP server refuses connections
- **WHEN** a verification email is queued
- **THEN** sign-up still answers 202
- **AND** the email is sent once the server is back within 24 hours, with the link still valid if it has not expired

### Requirement: Each environment has its own mail transport

Every environment SHALL send account email through the Gmail SMTP account set in its settings, as `QuantSim <alimazhar3005+QuantSim@gmail.com>`, with the SMTP password kept only in the encrypted secrets (NFR-SEC-003). Until the password is set, mail SHALL wait in the queue rather than be attempted. Every link SHALL point at that environment's own website.

#### Scenario: A DEV sign-up

- **WHEN** someone signs up on DEV
- **THEN** the verification email is sent from `alimazhar3005+QuantSim@gmail.com` to the address given
- **AND** its link opens `https://develop.quantsim-4hz.pages.dev/verify-email#...`

#### Scenario: Missing SMTP settings

- **GIVEN** an environment's SMTP host, username or password is not set
- **WHEN** the platform starts
- **THEN** it refuses to start with a message naming the missing setting, rather than accepting sign-ups it cannot email

### Requirement: Mail volume is limited per email address

The platform SHALL send at most 3 account emails to one address per hour, whatever route triggers them. Requests beyond that SHALL get the route's usual answer, with no extra email sent, so the limit itself reveals nothing.

#### Scenario: Repeated forgot-password requests

- **WHEN** forgot-password is sent 5 times in an hour for `sara@example.com`
- **THEN** all 5 responses are the same 202, and only 3 emails are sent

### Requirement: The reset email leads straight to the change-password page

The reset email SHALL be sent to the account's email address. It SHALL contain a "Change password" button whose link opens the web app's set-password page for that environment, and the plain URL as text below it.

#### Scenario: Forgot password from the sign-in page

- **GIVEN** an active user `sara.k` with email `sara@gmail.com`
- **WHEN** she presses "Forgot password?" and submits `sara@gmail.com`
- **THEN** an email from `alimazhar3005+QuantSim@gmail.com` reaches `sara@gmail.com`
- **AND** its "Change password" button opens `/set-password` with the token
- **AND** setting a new password there lets her sign in with it

### Requirement: Unverified sign-ups expire

A self sign-up whose email is still unverified 7 days after creation SHALL be removed by a daily clean-up, freeing its username and email. The removal SHALL be audited (FR-PLT-007) and published as `user.expired`. Invited accounts SHALL be kept until an admin deactivates them.

#### Scenario: An abandoned sign-up frees the username

- **GIVEN** `sara.k` signed up 8 days ago and never verified
- **WHEN** the daily clean-up runs
- **THEN** the account is gone, its audit history keeps the deletion, and a new sign-up may use `sara.k`

#### Scenario: Invited accounts are not removed

- **GIVEN** `omar` was invited 30 days ago and never used the link
- **WHEN** the clean-up runs
- **THEN** `omar` still exists with status `invited`
