# Lane B's contracts, copied for Lane A's tests

Byte-identical copies, never edited by hand (`-text` in `.gitattributes` keeps the bytes):

- `replay_ticks_2020.json`, `synthetic_ticks.json`: the recorded fixtures (C3), from `contracts/fixtures/`.
- `market.tick.v1.schema.json`: the tick schema (C1), from `contracts/events/` in the contract pull
  request #80, not yet merged. When #80 merges, the tests read it from `contracts/events/` and this
  copy is deleted.
