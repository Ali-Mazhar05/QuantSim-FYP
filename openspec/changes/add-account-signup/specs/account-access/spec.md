# Spec Delta

## Purpose

How a person gets a QuantSim account and a signed-in session: self sign-up for non-admin accounts without revealing which emails are registered, sign-in by username or email for verified accounts only, and the web pages that do this with no demo fallback (FR-PLT-001, FR-PLT-004, FR-PLT-005, NFR-SEC-004).

## ADDED Requirements

### Requirement: Self sign-up creates an unverified non-admin account

The platform SHALL accept a public sign-up with a username, an email, a password and an account type, and create an account with that role whose email is not yet verified (FR-PLT-001). It SHALL then queue a verification email and answer 202 "Check your email to finish creating your account". The account SHALL be audited and published as `user.created` with source `signup` (FR-PLT-006).

#### Scenario: A new person signs up as a Quant

- **GIVEN** no account uses the username `sara.k` or the email `sara@example.com`
- **WHEN** a sign-up is sent with username `sara.k`, email `sara@example.com`, a 14-character password and account type `quant`
- **THEN** the response is 202 with the "check your email" message and no tokens
- **AND** an account `sara.k` exists with role `quant` and status `invited` (email not verified)
- **AND** one verification email to `sara@example.com` is queued
- **AND** a `user.created` event with source `signup` is published

#### Scenario: The password is never stored or returned in plain text

- **WHEN** a sign-up succeeds
- **THEN** the stored credential is an Argon2id hash (NFR-SEC-004)
- **AND** the password does not appear in the response, the email, the event, the audit entry or the logs

### Requirement: Quant and Analyst sign-ups wait for admin approval

A self sign-up as `viewer` SHALL be able to sign in as soon as its email is verified. A self sign-up as `quant` or `analyst` SHALL also need an admin's approval. Until then, a correct password on a verified account SHALL get 403 `urn:quantsim:problem:approval-pending` with no tokens. Accounts created by an admin SHALL need no approval.

#### Scenario: Viewer signs in right after verifying

- **GIVEN** `vera` signed up as `viewer` and opened her verification link
- **WHEN** she signs in with her password
- **THEN** the response is 200 with a token pair

#### Scenario: Quant waits for approval

- **GIVEN** `sara.k` signed up as `quant` and opened her verification link
- **WHEN** she signs in with her password before an admin approves her
- **THEN** the response is 403 of type `approval-pending` with no tokens
- **AND** her status is `pending`

#### Scenario: Waiting screen in the web app

- **GIVEN** the platform answers 403 `approval-pending`
- **WHEN** the sign-in form is submitted
- **THEN** the app shows the POC-style "Waiting for admin approval" screen naming the requested role, with "Back to sign in"

### Requirement: Sign-up fields are validated

The platform SHALL refuse a sign-up with 422, naming the field, unless the fields follow these rules:
- **Username:** 3-40 characters of `a-z 0-9 . _ -`, lowered first.
- **Email:** a valid address.
- **Password:** 12-1024 characters.
- **Account type:** `viewer`, `analyst` or `quant`.

`admin` SHALL never be accepted.

#### Scenario: Admin cannot be chosen at sign-up

- **WHEN** a sign-up is sent with account type `admin`
- **THEN** the response is 422 and no account or email is created

#### Scenario: Invalid fields are refused

- **WHEN** a sign-up is sent with any of these:
  - a 2-character username;
  - a username containing a space;
  - an email without `@`;
  - an 11-character password;
  - a missing account type.
- **THEN** the response is 422 and names the invalid field, and no account or email is created

### Requirement: Sign-up does not reveal which emails have accounts

A sign-up with a valid body SHALL get the same 202 whether or not its email already belongs to an account. A taken email SHALL create nothing and instead email that address: "you already have an account" if it is verified, or a fresh verification link if it is not. A taken username SHALL get 409, because usernames are shown inside the app.

#### Scenario: Sign-up with an email that already has a verified account

- **GIVEN** a verified account with email `sara@example.com`
- **WHEN** a sign-up is sent with username `newname` and email `Sara@Example.com`
- **THEN** the response is the same 202 as for a new email
- **AND** no account is created
- **AND** an "already have an account" email to `sara@example.com` is queued

#### Scenario: Sign-up with an email that has an unverified account

- **GIVEN** an unverified account with email `sara@example.com`
- **WHEN** a sign-up is sent with that email
- **THEN** the response is the same 202, no second account is created, and a new verification link for the existing account is queued

#### Scenario: Taken username

- **GIVEN** an account with username `sara.k`
- **WHEN** a sign-up is sent with username `SARA.K` and an unused email
- **THEN** the response is 409 "That username is already taken." and no email is queued

### Requirement: Sign-up can be switched off and is limited per client

An environment SHALL be able to switch self sign-up off, after which the route answers 404 while sign-in, invitations and password reset keep working. The platform SHALL refuse more than the configured number of sign-up attempts from one client address within the configured window (default 10 per hour) with 429 and `retry_after_seconds`. The client address SHALL come from the gateway's forwarded-for header, and from no header a caller can set directly.

#### Scenario: Too many sign-ups from one address

- **GIVEN** the limit is 10 per hour
- **AND** 10 sign-up attempts came from one address within the last hour
- **WHEN** an eleventh attempt arrives from that address
- **THEN** the response is 429 with `retry_after_seconds` and nothing is created
- **AND** a sign-up from a different address is still accepted
- **AND** sign-ins from either address are not limited by this counter

#### Scenario: Sign-up switched off

- **GIVEN** `QS_SIGNUP_ENABLED` is false
- **WHEN** a sign-up is sent
- **THEN** the response is 404
- **AND** existing users can still sign in and reset their password

#### Scenario: The limit store is down

- **GIVEN** Redis cannot be reached
- **WHEN** a sign-up is sent
- **THEN** the response is 503 and nothing is created, so the limit is never silently skipped

### Requirement: Sign-in accepts a username or an email and needs a verified email

The platform SHALL sign a user in by username or by email, ignoring letter case, with the same password check, lockout and deactivation rules for both (FR-PLT-004). Failures:
- An unknown account, a wrong password or a deactivated account SHALL all get the same 401 message.
- A correct password on an account whose email is not verified SHALL get 403 `urn:quantsim:problem:email-unverified` and no tokens. This tells the caller only what they could already prove with the password.

#### Scenario: Sign in with the email

- **GIVEN** a verified, active user `sara.k` with email `sara@example.com`
- **WHEN** a sign-in is sent with `Sara@Example.com` and the correct password
- **THEN** the response is 200 with a token pair for `sara.k`

#### Scenario: Unverified account with the correct password

- **GIVEN** an unverified account `sara.k`
- **WHEN** a sign-in is sent with the correct password
- **THEN** the response is 403 of type `email-unverified` with no tokens

#### Scenario: Unverified account with a wrong password

- **GIVEN** an unverified account `sara.k`
- **WHEN** a sign-in is sent with a wrong password
- **THEN** the response is the ordinary 401, and the failure counts toward lockout

#### Scenario: Wrong passwords by username and email add up to one lockout

- **GIVEN** a verified user `sara.k` whose lockout threshold is 5 failures
- **WHEN** 5 sign-ins with a wrong password are sent, some by username and some by email
- **THEN** the next sign-in with the correct password returns 429 until the lock ends

#### Scenario: Deactivated and unknown accounts look the same

- **WHEN** a sign-in is sent for a deactivated account with its correct password, and another for an email no account uses
- **THEN** both responses are 401 with the same message

### Requirement: The web app uses real accounts only

The web app SHALL be usable only through a real session from the platform. There SHALL be no demo mode, no "Demo as" role choice on the sign-in page, and no mock-profile fallback (FR-PLT-005). A signed-in user may still preview the app as an equal or lower role from the top bar.

#### Scenario: The backend cannot be reached

- **GIVEN** the platform API is not reachable from the browser
- **WHEN** someone submits the sign-in form
- **THEN** the page stays on sign-in and shows "Cannot reach the QuantSim server"
- **AND** no page behind sign-in can be opened

#### Scenario: A page is opened without a session

- **GIVEN** no stored session, or a refresh token the platform refuses
- **WHEN** someone opens `/dashboard` directly
- **THEN** they are sent to `/login`

#### Scenario: The sign-in page

- **WHEN** `/login` is shown
- **THEN** it has the POC card with "Username or email", "Password" and a "Sign In" button, plus "Forgot password?" and "Create account" links
- **AND** the fields start empty, with no role picker

#### Scenario: Sign-in on an unverified account

- **GIVEN** the platform answers 403 `email-unverified`
- **WHEN** the sign-in form is submitted
- **THEN** the page says "Verify your email first" with a "Send the link again" button that calls resend-verification

### Requirement: The web sign-up page

The web app SHALL offer `/signup` in the POC sign-in style:
- a card with Username, Email, Password and Confirm password;
- an account-type grid of Viewer, Analyst and Quant with the POC descriptions, Quant chosen by default;
- a "Create account" button and a "Sign in" link.

The page SHALL check fields before sending and show the platform's errors on the form. On a 202 it SHALL show the "Check your email" screen.

#### Scenario: Successful sign-up from the page

- **WHEN** a person fills in valid fields, picks Analyst, and presses "Create account"
- **THEN** the "Check your email" screen names the address and offers "Send the link again" and "Back to sign in"

#### Scenario: Passwords do not match

- **WHEN** Password and Confirm password differ
- **THEN** "Passwords do not match" is shown under Confirm password and nothing is sent

#### Scenario: Taken username shown on the form

- **GIVEN** the platform answers 409
- **WHEN** the form is submitted
- **THEN** "That username is already taken." is shown under Username and the typed values stay

#### Scenario: Sign-up closed or limited

- **WHEN** the platform answers 404 or 429
- **THEN** the form shows "Sign-up is closed on this environment", or "Too many attempts, try again in N minutes"

#### Scenario: No Admin choice on the page

- **WHEN** `/signup` is shown
- **THEN** the account-type grid has exactly Viewer, Analyst and Quant

#### Scenario: Already signed in

- **GIVEN** a valid session
- **WHEN** `/signup` or `/login` is opened
- **THEN** the app goes to `/dashboard`
