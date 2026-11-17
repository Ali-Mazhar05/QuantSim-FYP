# ADR 08: Prices

Status: Proposed. Date: 2026-11-17. Owner: Lane B. Consumer: Lane A.

## Context

Ticks must give strategies prices that are continuous across splits and dividends, and a source fingerprint that tells a consumer when the data it read has changed. Facts in the code on `develop`: the `bar` table keeps raw and adjusted values; the adjusted columns are nullable; the vendor restates adjusted prices backwards at every dividend or split, and the pipeline updates them in place without creating a revision (`runner.py`); `content_hash` covers raw vendor values only, on purpose (`cleaning.py`, ingestion plan D18).

## Decision

- Ticks use the split- and dividend-adjusted open, high, low, close and volume, as decimal strings.
- The source fingerprint is xxh3 over the ordered served values `(instrument_id, session_date, revision, adj_open, adj_high, adj_low, adj_close, adj_volume)` of the environment's instruments inside its window. It changes when a bar revision lands or when the vendor restates adjusted prices inside the window, and not for other instruments or dates outside the window. The revision-only rule in the guide is not enough, because a restatement changes tick prices without a revision.
- Activation freezes the fingerprint at that moment. A consumer compares the frozen value with `X-Source-Fingerprint` on each page and decides what to do on a mismatch.
- An environment whose window contains a bar with a missing adjusted value cannot be activated and its feed refuses with 422 `missing_adjusted_prices` and counts per symbol. Raw prices are never substituted silently.
- A symbol with no bar on a session has no tick that session; `seq` stays gap-free over the ticks emitted; activation records the missing-session count. Consumers must tolerate an absent symbol.
- `ts` is the session close in UTC. Only daily environments can be activated for replay; hourly and tick environments get 422.
- Snapshotting the window's ticks at activation is deferred (it is additive); build it if a rehearsal shows replays changing between runs.

## Consequences

- Replaying an old window can change after a dividend; the fingerprint makes that visible, and a stored run records the fingerprint it used.
- The fingerprint is computed on read and must be measured on a 40-name, 2,900-session window.
- Awaiting confirmation from Lane A: missing adjusted values and missing sessions.
