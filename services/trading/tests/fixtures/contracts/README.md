# Lane B's contracts, copied for Lane A's tests

Byte-identical copies, never edited by hand (`-text` in `.gitattributes` keeps the bytes):

- `replay_ticks_2020.json`, `synthetic_ticks.json`: the recorded fixtures (C3), from `contracts/fixtures/`.
  The file adapter checks these exact bytes, so they are kept here unconverted.

The tick schema (C1) is read from `contracts/events/` itself, and the feed routes (C2) from the
market OpenAPI (`frontend/src/services/generated/market/openapi.json`).
