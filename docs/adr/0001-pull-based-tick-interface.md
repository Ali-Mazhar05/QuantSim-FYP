# ADR 01: Pull-based tick interface

Status: Proposed. Date: 2026-11-17. Owner: Lane B. Consumer: Lane A (trading engine).

## Context

The trading engine reads market ticks from two sources that look the same to it: historical replay (served by `market`) and synthetic paths (served by `simulation`). The interface could push ticks (a stream or the message broker) or let the consumer pull them page by page. Both services must give the same ticks for the same inputs so that a run can be repeated and its log hash compared (FR-SIM-01, replay determinism in the report's validation plan).

## Decision

Consumers pull. Ticks follow one schema, `market.tick.v1` (`contracts/events/`), and are read with `after_seq`:

- Replay: `GET /api/market/environments/{id}/ticks?after_seq=&limit=`. Synthetic: `GET /api/simulation/runs/{id}/ticks?path=&after_seq=&limit=`.
- Page size: `limit` defaults to 500, at most 2000, the convention the market service already uses for every list (decision log DL-008). Body `{items, next_after_seq}` where `next_after_seq` is null on the last page. Header `X-Source-Fingerprint` carries the current fingerprint of the data served (see ADR 08).
- Order is `(session, symbol)`. `seq` starts at 1 and has no gaps per environment and path. `session` is the zero-based index of the session within the environment's ordered session list. A symbol with no bar on a session has no tick that session (see ADR 08).
- Prices and volume are decimal strings. Consumers ignore unknown fields.
- A live push stream is not part of Iteration 2. The only stream is the optional replay clock stream used by the Replay page, which can be replaced by polling (cut order).

## Consequences

- The engine controls its own pace and can resume from the last `seq` it applied; two reads of the same data are byte-identical.
- No broker topic is needed for ticks, which keeps the free-tier footprint small.
- After the contract freeze (J1) the schema changes only by an additive pull request approved by Lane B and every consumer; a breaking change ships as `v2` beside `v1`.
- Awaiting confirmation from Lane A: the meaning of `session` and the paging numbers.
