# ADR 05: Strategy type

Status: Accepted. Date: 2026-11-20. Owner: Lane A. Consumers: Lane B (frontend strategy pages, ADR 06 strategy-type select).

## Context

Quants need to define and edit strategies in the web app, and a run must be reproducible from what is stored (A-FR-12, A-FR-13). User-supplied code would need sandboxing and would make reproducibility depend on code that can change; a fixed set of built-in strategies with typed parameters avoids both and is enough for the iteration's demo.

## Decision

- A strategy is a `kind` plus `params` (JSONB). Four built-in kinds: `buy_and_hold`, `ma_crossover`, `momentum` (with a max-position cap, A-FR-03) and `mean_reversion`. The database refuses any other kind.
- Each kind has a strict Pydantic parameter model (unknown keys refused, no floats for money). A bad parameter gives 422 whose error location names the field (A-FR-01). Parameters are stored in canonical form, defaults filled in and decimals as strings.
- Strategies are pure and stateless: at session `t` they read a history-only view that raises `LookAheadError` for anything after `t` (A-FR-02), and they return market orders sized in whole shares at the latest close, keeping a cash buffer (default 2%) for costs. No clock, randomness or I/O, and a fixed decimal context, so a rerun places the same orders.
- A strategy cannot be edited (409) once a portfolio that uses it has written its log, so every log stays reproducible from its stored spec. Only its owner or an admin may edit it.

## Consequences

- A new kind needs code, a parameter model, tests and a migration that widens the kind check; there is no user-defined strategy code.
- Changing a strategy after it has been run means creating a new one.
- Implemented in `services/trading/src/qs_trading/domain/strategies/` (A12, #88) and the strategies API (A16, #97).
