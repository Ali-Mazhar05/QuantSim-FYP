# Platform service (M0)

Owns users and roles, signs every access token, and publishes the public keys every
other service verifies tokens with (FR-PLT-001..008). Built on `libs/qs_template`.

## API (`/api/platform`)

| Method and path | Who | Purpose |
|---|---|---|
| `POST /auth/login` | anyone | Username and password in; RS256 access token (15 minutes) and refresh token (12 hours) out |
| `POST /auth/refresh` | anyone with a refresh token | New access and refresh token; the old refresh token stops working, and reusing it ends the whole session |
| `POST /auth/logout` | anyone with a refresh token | Ends that session; always 204 |
| `GET /.well-known/jwks.json` | anyone | Public signing keys (current and retired) |
| `GET /auth/me` | signed in | The current user |
| `GET /users` | admin | List users (`include_inactive`, `limit`, `offset`) |
| `POST /users` | admin | Create a user |
| `GET /users/{id}` | admin | One user |
| `POST /users/{id}/deactivate` | admin | Deactivate; existing tokens stop working everywhere |
| `POST /users/{id}/reactivate` | admin | Reactivate |
| `PUT /users/{id}/role` | admin | Change role; existing tokens stop working everywhere |
| `GET /users/{id}/history` | admin | Every change to the user: what, when, by whom, from which request |
| `GET /health`, `GET /ready` | anyone | Liveness (with build hash) and readiness (database, Redis) |

Interactive documentation: `/api/platform/docs`.

## Rules

- **Passwords**: Argon2id, at least 12 characters, never logged, never in the audit trail.
- **Sign-in**: wrong password, unknown user and deactivated account give the same answer
  and take the same time. After `QS_LOGIN_MAX_FAILURES` failures the account is locked for
  `QS_LOGIN_LOCKOUT_SECONDS` (HTTP 429).
- **Roles**: `admin`, `quant`, `analyst`, `viewer`, enforced by a database constraint.
- **Revocation**: deactivation and role changes record a cut-off time in Redis; every
  service refuses tokens issued before it. If Redis is unreachable, requests fail closed.
- **Last admin**: the last active admin cannot be deactivated or demoted, even by two
  admins acting at the same moment.
- **Events** (topic `quantsim.platform.user`, key = user id): `user.created`,
  `user.deactivated`, `user.reactivated`, `user.role_changed`, written through the outbox
  in the same transaction as the change.
- **Audit**: a database trigger records every insert, update and delete on `users` with
  the acting admin and request id.

## Configuration (environment)

| Variable | Required | Meaning |
|---|---|---|
| `QS_DATABASE_URL` | yes | `postgresql+asyncpg://platform:<password>@postgres:5432/platform` |
| `QS_REDIS_URL` | yes | Redis holding the revocation list |
| `QS_SIGNING_KEY` | yes | RS256 private key, base64-encoded PEM (`qs-platform generate-signing-key`) |
| `QS_SIGNING_KEY_ID` | yes | Key id published in the JWKS, e.g. `platform-2026-10` |
| `QS_RETIRED_PUBLIC_KEYS` | no | JWKS JSON of retired keys, during a rotation |
| `QS_KAFKA_BOOTSTRAP_SERVERS` | relay | Redpanda address for the outbox relay |
| `QS_ACCESS_TOKEN_TTL_SECONDS` | no | Default 900 |
| `QS_REFRESH_TOKEN_TTL_SECONDS` | no | Default 43200 (12 hours), renewed on each refresh |
| `QS_LOGIN_MAX_FAILURES`, `QS_LOGIN_LOCKOUT_SECONDS` | no | Defaults 5 and 900 |
| `QS_BOOTSTRAP_ADMIN_PASSWORD` | first deploy | Password of the first `admin`, created only when no active admin exists |

## Commands (container entrypoint `qs-platform`)

| Command | What it does |
|---|---|
| `serve` | HTTP API on port 8000 |
| `relay` | Publishes outbox events to Redpanda |
| `bootstrap-admin` | Creates the first admin if there is none; safe on every deploy |
| `generate-signing-key` | Prints a new `QS_SIGNING_KEY` value |

Migrations: `alembic upgrade head` in the image's working directory, using
`DATABASE_URL` or `QS_DATABASE_URL`. The deploy runs migrations and `bootstrap-admin`
through the `platform-migrate` container before starting the new version.

## Rotating the signing key

1. `qs-platform generate-signing-key` and choose a new key id.
2. Put the current key's public JWK (from `/.well-known/jwks.json`) into
   `QS_RETIRED_PUBLIC_KEYS`.
3. Deploy with the new `QS_SIGNING_KEY` and `QS_SIGNING_KEY_ID`. Other services fetch the
   new key the first time they see its id; old tokens keep working until they expire.
4. After the token lifetime has passed, remove the retired key.

## Development

```bash
ci/scripts/python-ci.sh services/platform     # lint, types, tests (starts PostgreSQL)
ci/scripts/migration-check.sh platform        # migrations up, down and up again
```
