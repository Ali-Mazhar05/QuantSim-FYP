# Data hooks: the pattern every page uses

One hook per endpoint (or per resource), built on four things in this folder and `services/`:

| Piece | File | Rule |
|---|---|---|
| Typed call | `services/api/typed.ts` (`apiGet`, `apiPost`) | The path picks the parameters and the response from the generated types. Never hand-write an API response type. |
| Query key | `hooks/queryKeys.ts` | One factory per service: `[service, resource, ...params]`. Invalidate by prefix. |
| Hook | `hooks/useXxx.ts` | `useQuery({ queryKey, queryFn, enabled: authenticated })`; return a small view model, not the raw query. A write is a `useMutation` that invalidates the keys it changed. |
| Error | `hooks/apiError.ts` | `classifyError(error)` gives `kind` (`unauthenticated`, `forbidden`, `not_found`, `conflict`, `invalid`, `rate_limited`, `server`, `unreachable`, `unknown`), a message, `fieldErrors` for 422 and `retryAfterSeconds` for 429. A page shows its 403 state when `kind === 'forbidden'`. |

The cache is created once by `QueryProvider` (in `App`) and emptied on sign-out. Queries do not retry
and are fresh for 15 seconds; a query that needs retries sets `retry` itself.

## Adding a service or an endpoint

1. The service exports its OpenAPI: add it to `SERVICES` in `scripts/export-openapi.py`, then
   `uv run --all-packages python scripts/export-openapi.py`.
2. `npm run gen:api` (add the service's line to that script) and re-export its types in `services/generated/index.ts`.
3. Write the hook and its test. Do not skip the four page states: loading, data, empty, error (and 403).

## Keeping contracts honest

Three checks fail when an API and the frontend disagree: the service's own test
(`test_openapi_export.py`: the committed document is stale), `generated.test.ts` (the committed types are stale) and
`npm run typecheck` (a page uses a field that no longer exists). If you changed an API, regenerate and commit
both generated files.

## Tests with the mock backend

`setupMockServer()` from `test/mocks/server.ts` turns on MSW for a test file and makes any request without
a handler fail the test. Handlers live in `test/mocks/handlers.ts`; fixtures are typed against the generated
schema. When `contracts/fixtures/` (C3) exists, handlers load those recorded files instead.
