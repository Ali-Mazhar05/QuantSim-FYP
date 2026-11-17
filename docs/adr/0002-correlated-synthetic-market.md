# ADR 02: Correlated synthetic market

Status: Proposed. Date: 2026-11-17. Owner: Lane B. Maths from Lane C (K5 calibration).

## Context

The synthetic market must produce many price paths for several instruments that move together as they do in real data (FR-SIM-02), reproducibly and independent of how many workers run the job. Independent instruments would understate portfolio risk.

## Decision

- Shocks are correlated with a Cholesky factor: `Z = L e` with `L L^T = rho`, where `rho` comes from the market correlation API (C4) over the calibration window.
- Paths use exact discretisations over `dt = 1/252`: GBM `S(t+dt) = S(t) exp((mu - sigma^2/2) dt + sigma sqrt(dt) Z)`; OU `X(t+dt) = theta + (X(t) - theta) e^(-kappa dt) + sigma sqrt((1 - e^(-2 kappa dt)) / (2 kappa)) Z`; Merton GBM with drift `mu - sigma^2/2 - lambda k` plus `N ~ Poisson(lambda dt)` jumps `Y ~ N(mu_J, sigma_J^2)`, `k = exp(mu_J + sigma_J^2/2) - 1`.
- OU is simulated on log price and published as `exp(X)`, because the calibration (K5 `fit_ou`) fits log prices.
- A matrix that is not positive semi-definite is repaired by clipping eigenvalues at 1e-8 and rescaling to a unit diagonal. The run records whether a repair happened, the smallest eigenvalue before, and the size of the change.
- Work is split into shards of 250 paths. One `SeedSequence(seed)` spawns one child per shard; each shard spawns three streams (normals, Poisson counts, jump sizes), so GBM and Merton share the same normal shocks. A shard draws one array of shape (paths, steps, instruments) in a fixed order. The instrument list is part of the run configuration, so a different list is a different run.
- Workers set `OMP_NUM_THREADS=1` and leave one core for the API.

## Consequences

- The same seed and configuration give identical output with 1, 2 or 4 workers; this is tested.
- Generator moments are tested against closed form at 20,000 paths (within 3 standard errors) and shock correlation within 0.02.
- Regime switching is out of scope (shown as Extended on the Models page only).
- Awaiting confirmation from Lane C: OU on log price and the K5 parameter names.
