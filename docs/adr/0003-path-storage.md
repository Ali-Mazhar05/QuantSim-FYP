# ADR 03: Path storage

Status: Proposed. Date: 2026-11-17. Owner: Lane B. Consumer: Lane A (path tick feed).

## Context

A run produces paths x steps x instruments values. Storing every value for large runs would exhaust a laptop-hosted, free-tier database, but small runs need exact paths for the trading engine and the results page. A run is reproducible from its seed and configuration, so values can also be regenerated.

## Decision

- A run keeps every value when `n_paths * n_steps <= 252,000` per instrument and `n_instruments <= 10`; otherwise it keeps the seed, the configuration and per-step quantiles only and regenerates paths on demand. A regenerated path equals a stored one bit for bit.
- Per-step quantiles (p1, p5, p25, p50, p75, p95, p99) are stored for every run.
- Stored values live in an ordinary table keyed by run, instrument, path and step, written with `COPY`. The guide proposed a hypertable; there is no time column that helps the access patterns (all steps of one path, one step across paths), so a hypertable is not used. Revisit only if a measurement on the demo run (5 names, 1,000 paths, 252 steps) shows a problem.
- The median path a portfolio binds to is chosen deterministically: rank the paths by the terminal value of the equal-weighted basket of normalised prices, take the lower-median rank, break ties by the lowest path index. Its index is stored on the run as `median_path_index`.

## Consequences

- The demo run stores about 1.26 million rows; larger runs cost almost nothing to keep.
- The path tick feed works the same for stored and regenerated paths.
- Awaiting confirmation from Lane A: the median-path rule.
