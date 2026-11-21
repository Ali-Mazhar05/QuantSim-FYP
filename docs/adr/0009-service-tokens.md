# ADR 09: Service tokens

Status: Accepted. Date: 2026-11-20. Owner: Lane A. Consumers: Lanes B and C (any worker that calls another service).

## Context

Background workers call other services with no user behind the request, for example a trading run reading market ticks half an hour after it was submitted (A-FR-19). They cannot reuse the submitting user's access token, which expires, and every service already verifies platform-signed RS256 tokens locally. Workers need to call each other in week 2, before real service credentials were ready.

## Decision

- Workers call other services through the kit's `ServiceClient` (K3): per-request timeouts, retries with jittered backoff for safe methods or requests carrying an idempotency key, and a circuit breaker. Every failure is one `ServiceCallError` (`upstream-down`, `circuit-open`, `upstream-error`), so a provider being down ends a job in a controlled way.
- Until real tokens exist, DEV uses one shared static token, `QS_SERVICE_TOKEN` (at least 32 characters). The client refuses to load it outside `local` and `dev`, and a service configured with it in test, acc or prod refuses to start. Services accept it as a read-only service principal (viewer role), compared in constant time; any other value is refused with 401.
- Real tokens (client credentials): a calling service posts `{"grant_type": "client_credentials", "client_id": "<service>", "client_secret": "..."}` to `POST /api/platform/service-tokens` and gets an RS256 token signed with the platform's user-token key: `sub="service:<name>"`, `kind="service"`, `role="viewer"`, `iss`, `aud`, `jti`, `iat`, and a 10-minute `exp` (`QS_SERVICE_TOKEN_TTL_SECONDS`, 1 to 15 minutes).
- Client secrets: one random 256-bit secret per calling service per environment (`<SERVICE>_SERVICE_CLIENT_SECRET` in the encrypted secrets). The caller reads it as `QS_SERVICE_CLIENT_SECRET`; the platform reads all of them as `QS_SERVICE_CLIENT_SECRETS` (`trading=...,risk=...`), keeps only their SHA-256 in memory and compares in constant time. No database table: the platform's environment already holds the signing key, so a hashed store would add work without reducing exposure.
- Bad secrets are counted per client address like failed sign-ins (`QS_LOGIN_MAX_FAILURES`, `QS_LOGIN_LOCKOUT_SECONDS`): over the limit the address gets 429; Redis being down fails closed (503). Each issue and refusal is logged with the service name and token id, never the secret or token.
- Every service's `Authenticator` accepts these tokens through the same JWKS check as user tokens, as a viewer service principal (`is_service`, `service_name`). A token with `kind` must name a known service with `sub="service:<name>"` and the viewer role; a token without it must name a user id, so neither can pass for the other. Each service principal has a fixed id, so the user revocation list can also cut a service off.
- The kit's `ClientCredentialsToken` fetches, caches and renews the token 60 s before expiry (at most half its lifetime); concurrent callers share one fetch, and a failed renewal keeps using a still-valid token. `service_tokens_from_settings` returns it when `QS_SERVICE_TOKEN_URL` and `QS_SERVICE_CLIENT_SECRET` are set, else the DEV static token, else fails at start-up.
- The static token stays accepted in DEV until every caller uses the factory, then it is removed before TEST.

## Consequences

- Calls between services are reads only, one hop deep, so a viewer-level service principal is enough for now.
- With real tokens a receiving service knows which service called (`service_name`, logged as `calling_service`); calls with the static token still cannot be told apart, and `X-Calling-Service` is for logs only.
- A worker that starts a job and reads another service half an hour later keeps working: the provider renews tokens as needed, and only the token endpoint must be reachable.
- A new calling service needs a secret in every environment and an entry in the platform's `QS_SERVICE_CLIENT_SECRETS` (compose); a known service with no secret cannot get a token. Rotating a secret means updating it and redeploying the platform and the caller together.
- Implemented in `libs/qs_template/src/qs_template/service_client.py`, `auth.py` and `config.py` (K3) and `services/platform/src/qs_platform/service_tokens.py`.
