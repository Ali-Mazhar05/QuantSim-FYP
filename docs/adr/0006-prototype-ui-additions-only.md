# ADR 06: Prototype UI additions only

Status: Accepted. Date: 2026-11-17. Owner: Lane B.

## Context

The prototype pages are already approved as the product's look. Iteration 2 wires them to real services. Redesigning them would cost time and would re-open an approved layout.

## Decision

- Router, navigation and layout stay as they are. Lane B changes pages only by adding: a strategy-type select, an interval selector (daily, weekly, monthly, yearly) with a date range, and replay controls (play, pause, 1x/5x/20x, seek). No other layout change.
- Every Lane B page shows loading, empty, error and 403 states, never conveys status by colour alone, and has stable test ids for the end-to-end tests.
- Other lanes add their routes and navigation entries by small pull requests straight to `develop`, reviewed by Lane B within a day.
- The replay clock lives on the server: a session stores an anchor session index, the server time of that anchor, the speed (1, 5 or 20) and the state. Position is computed on read as `min(anchor_index + floor(elapsed_seconds x speed), last_index)` while playing, so a reload resumes at the server position and no background task is needed. Pause, speed change and seek each write a new anchor.
- Regime switching stays visible as an Extended item on the Models page.

## Consequences

- The Replay page can poll the session; a live stream is optional and cut-able.
- Controls are disabled with a readable explanation for roles that lack the capability.
