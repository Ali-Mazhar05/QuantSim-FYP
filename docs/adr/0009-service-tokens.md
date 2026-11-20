# ADR 09: Service tokens

Status: Accepted. Date: 2026-11-20. Owner: Lane A. Consumers: Lanes B and C (any worker that calls another service).

## Context

Background workers call other services with no user behind the request, for example a trading run reading market ticks half an hour after it was submitted (A-FR-19). They cannot reuse the submitting user's access token, which expires, and every service already verifies platform-signed RS256 tokens locally. Real service credentials need work in the Platform service; workers need to call each other in week 2.

## Decision

- Workers call other services through the kit's `ServiceClient` (K3): per-request timeouts, retries with jittered backoff for safe methods or requests carrying an idempotency key, and a circuit breaker. Every failure is one `ServiceCallError` (`upstream-down`, `circuit-open`, `upstream-error`), so a provider being down ends a job in a controlled way.
- Until real tokens exist, DEV uses one shared static token, `QS_SERVICE_TOKEN` (at least 32 characters). The client refuses to load it outside `local` and `dev`, and a service configured with it in test, acc or prod refuses to start. Services accept it as a read-only service principal (viewer role), compared in constant time; any other value is refused with 401.
- Real tokens follow by 2 Dec as an additive change: the Platform service issues short-lived client-credential tokens to each service, verified like user tokens. The static token is removed before TEST.

## Consequences

- Calls between services are reads only, one hop deep, so a viewer-level service principal is enough for now.
- Until real tokens land, DEV cannot tell which service made a call from the token alone; `X-Calling-Service` is sent for logs only.
- Implemented in `libs/qs_template/src/qs_template/service_client.py` and `auth.py` (K3, #85, awaiting review by Lanes B and C).
