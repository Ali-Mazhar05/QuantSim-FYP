# Spec Delta

## Purpose

How an administrator promotes and demotes users between Viewer, Analyst, Quant and Admin, with guards, immediate effect and an audit trail (FR-PLT-003, FR-PLT-005, FR-PLT-006).

## ADDED Requirements

### Requirement: Only role managers change roles

The platform SHALL let a user with the `manage_roles` capability set any user's role to Viewer, Analyst, Quant or Admin, including promotion to Admin (FR-PLT-003). Every other user SHALL be refused with 403 (FR-PLT-005).

#### Scenario: Admin promotes a Viewer to Quant

- **GIVEN** an admin and an active Viewer `sara.k`
- **WHEN** the admin sets `sara.k`'s role to `quant`
- **THEN** the response is 200 with role `quant`
- **AND** a `user.role_changed` event is published with `previous_role` `viewer` and `role` `quant`
- **AND** the audit history of `sara.k` shows the role change, attributed to the admin

#### Scenario: Admin promotes a Quant to Admin

- **GIVEN** an admin and an active Quant `omar`
- **WHEN** the admin sets `omar`'s role to `admin`
- **THEN** the response is 200 with role `admin`
- **AND** after signing in again `omar` has the `manage_users` and `manage_roles` capabilities

#### Scenario: A non-admin tries to change a role

- **GIVEN** a signed-in Quant
- **WHEN** they ask to set their own role, or anyone's role, to `admin`
- **THEN** the response is 403 and nothing changes

#### Scenario: Unknown user or unknown role

- **WHEN** an admin sets the role of an id no user has
- **THEN** the response is 404
- **WHEN** an admin sends the role `superuser`
- **THEN** the response is 422

### Requirement: Admins approve or reject pending sign-ups

A holder of `manage_users` SHALL see self sign-ups waiting for approval, and SHALL be able to approve or reject each one.
- **Approve:** records who approved it and when, publishes `user.approved`, and emails the user "Your QuantSim account is approved" with a sign-in link.
- **Reject:** deactivates the account, publishes `user.rejected`, and sends no email.

Both actions SHALL be audited, and both SHALL be refused with 403 for anyone without `manage_users`.

#### Scenario: Admin approves a Quant

- **GIVEN** `sara.k` is verified and pending as `quant`
- **WHEN** an admin approves her
- **THEN** her status becomes `active`
- **AND** an approval email is queued for her
- **AND** her next sign-in returns a token pair with the `quant` capabilities

#### Scenario: Admin rejects an Analyst

- **GIVEN** `omar` is pending as `analyst`
- **WHEN** an admin rejects him
- **THEN** his status becomes `disabled` and his sign-ins get the ordinary 401

#### Scenario: Pending users on the Users page

- **GIVEN** two pending sign-ups
- **WHEN** an admin opens `/admin/users`
- **THEN** both rows show a "Pending" badge in the POC badge style, with Approve and Reject buttons, and the page header shows "2 awaiting approval"

#### Scenario: Approving a user who is not pending

- **WHEN** an admin approves an account that is already active, or one whose email is unverified
- **THEN** the response is 409 and nothing changes

### Requirement: The last administrator cannot be demoted

The platform SHALL refuse a role change that would leave no active Admin, with 409. Two admins demoting each other at the same moment SHALL NOT both succeed.

#### Scenario: Demoting the only admin

- **GIVEN** exactly one active admin
- **WHEN** that admin sets their own role to `quant`
- **THEN** the response is 409 "The last active administrator cannot be deactivated or demoted." and the role stays `admin`

#### Scenario: Two admins demote each other at once

- **GIVEN** exactly two active admins A and B
- **WHEN** A demotes B and B demotes A concurrently
- **THEN** exactly one request succeeds and the other gets 409
- **AND** one active admin remains

### Requirement: A role change takes effect at once

When a role changes, the platform SHALL end that user's existing sessions, so the old role is honoured by no service after the token-check window and the user must sign in again (FR-PLT-002, FR-PLT-004). Setting the role a user already has SHALL change nothing and publish nothing.

#### Scenario: Demoted user's old token stops working

- **GIVEN** a signed-in Quant `omar` with an access token and a refresh token
- **WHEN** an admin demotes `omar` to `viewer`
- **THEN** `omar`'s old access token is refused with 401 within the token-check window
- **AND** `omar`'s old refresh token is refused with 401
- **AND** `omar`'s next sign-in carries the `viewer` capabilities

#### Scenario: Same role again

- **GIVEN** `sara.k` is a Quant
- **WHEN** an admin sets `sara.k`'s role to `quant`
- **THEN** the response is 200
- **AND** no event, audit entry or session cut-off happens

### Requirement: Role control on the Users page

The web Users page SHALL show a role selector (Viewer, Analyst, Quant, Admin) in each user's row only to users holding `manage_roles`. Everyone else sees the role as plain text. The selector SHALL confirm before demoting an Admin, show the platform's error if the change is refused, and keep the row at the role the platform reports.

#### Scenario: Admin changes a role from the page

- **GIVEN** an admin on `/admin/users`
- **WHEN** they choose Analyst in `sara.k`'s row
- **THEN** the row shows Analyst after the platform confirms, and a success notice appears

#### Scenario: Refused change rolls back in the page

- **GIVEN** the only admin on `/admin/users`
- **WHEN** they choose Quant in their own row and confirm
- **THEN** the platform's 409 message is shown and the row still shows Admin

#### Scenario: Previewing a lower role hides the control

- **GIVEN** an admin previewing the app as Analyst from the top bar
- **WHEN** they view any page
- **THEN** no role selector is offered, because previewing shows exactly what that role sees
