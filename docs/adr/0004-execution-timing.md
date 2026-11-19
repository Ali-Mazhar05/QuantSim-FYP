# ADR 04: Execution timing

Status: Accepted. Date: 2026-11-20. Owner: Lane A. Consumers: Lanes B and C (they read the fills and value series).

## Context

Environments serve daily bars (ADR 08). A strategy decides at session `t` after seeing that session's close, so filling an order at any price of session `t` would use information the strategy acted on and flatter the results. The engine must also give the same log, and the same final hash, for the same spec on the same data (A-FR-12), and a killed worker must resume to an identical log (A-FR-13), so execution has to be a pure function of the bars and the portfolio.

## Decision

- **Market orders** placed at session `t` fill at the open of the symbol's next session that the engine processes, moved against the trader by the slippage model. An order whose fill session has no bar for its symbol is rejected with `NO_PRICE`; it is not carried forward.
- **Limit orders** rest from `t + 1`. A buy fills at the open when the session opens at or below the limit (a gap through it), otherwise at the limit when the low reaches it; a sale mirrors this with the high. Slippage applies, but a limit fill is never worse than its limit. `expires_after` sessions after placement is the last session it may fill in; unfilled at the end of that session it gives `ORDER_EXPIRED` in the same session.
- **Placement checks:** a buy must be payable, costs included, at an estimate of its fill (a market buy at the last close plus slippage, a limit buy at its limit price); a sale may not exceed the shares held minus those already committed. Proceeds of market sales placed earlier in the same session count towards later buys. Long only, whole shares.
- **Fill-time check:** because the open can gap away from the close, every fill is checked against the books again; one that the portfolio can no longer pay for is rejected (`ORDER_REJECTED` with its `order_id`), so the books never go negative.
- **Costs** are `fixed + per_share × quantity + pct × notional` on the slipped price, each part rounded to cents, half to even. **Slippage** is fixed basis points, or volume based: `bps × min(quantity / bar volume, 1)`, with zero volume treated as full participation.

## Consequences

- No intraday execution or partial fills; a gap shows up as a fill at the open, and a halted or missing symbol gives `NO_PRICE` for market orders and is valued at its last close.
- Confirms ADR 08 for Lane A: a symbol with no bar on a session has no tick, and the engine tolerates it (tested on the A14 fixture, which has one).
- The volume model caps the literal formula for orders larger than the bar's volume.
- Implemented in `services/trading/src/qs_trading/domain/execution.py` (A11, #87) and the engine loop (A14, #92); verified live on DEV by the trading live check (#101).
