# Data hooks: the pattern every page uses

One hook per endpoint (or per resource), built on four things in this folder and `services/`:

| Piece | File | Rule |
|---|---|---|
| Typed call | `services/api/typed.ts` (`apiGet`, `apiPost`, `apiPut`) | The path picks the parameters and the response from the generated types. Never hand-write an API response type. The options take `headers` (e.g. `Idempotency-Key`) and a `signal`; pass the query's `signal` from `queryFn`. |
| Query key | `hooks/keys/<service>.ts` | One factory per service: `[service, resource, ...params]`. Invalidate by prefix. |
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

## Patterns for the cases every service has

**Sign-out and 403.** A 401 that is still a 401 after the one refresh the client tries ends the session:
`QueryProvider` clears the tokens, signs out and empties the cache. Hooks return `error` as a
`ClassifiedError`, so a page branches on `error.kind` (`forbidden` shows the 403 state, never a retry
button) and prints `error.message`.

**Keys and mocks per service.** Keys live in `hooks/keys/<service>.ts`, default handlers in
`test/mocks/handlers/<service>.ts`. A lane edits its own two files and adds one line to
`test/mocks/handlers/index.ts`.

**Paging.** The market API pages by `cursor` (`next_cursor` in the answer) or by `after_seq`. Use
`useInfiniteQuery` with `getNextPageParam` returning the next cursor, or `undefined` when there is none.
Never fetch "all pages" in a hook; a page that needs everything asks the server for an aggregate.

**202 and polling.** A job (a calibration, a run) answers `202` with an id. Poll the one resource with
`refetchInterval: (query) => (isFinished(query.state.data) ? false : 1000)` so polling stops by itself,
and keep the interval at one second or more. A page reload resumes from the server's state, not from
the page's memory.

**409.** `classifyError` gives `kind === 'conflict'`. Show the server's message and offer to reload the
resource; do not retry the write. An `Idempotency-Key` sent with a write makes a repeated submit return
the first answer instead of a 409.

**Money and prices are strings.** The API sends prices and amounts as decimal strings (`"187.4300"`).
Keep them as strings through the hook and the page; format for display only, and never add or compare
them as JavaScript numbers.
