# qs_quant

Pure quantitative maths shared by the QuantSim services: metrics and risk statistics
(K6, `qs_quant.metrics`) and model calibration (K5, `qs_quant.calibration`). No I/O, no
database, no network. The metrics need NumPy only; calibration also needs SciPy and
statsmodels, through the `calibration` extra. Formulas follow the Lane C guide §7.1–7.6.

| Package | Consumers | Install |
|---|---|---|
| `qs_quant.metrics` (K6) | trading (A16), simulation (B16) | `qs-quant` |
| `qs_quant.calibration` (K5) | simulation (B15) | `qs-quant[calibration]` |

## Use

In the consuming service's `pyproject.toml`:

```toml
dependencies = ["qs-quant", ...]

[tool.uv.sources]
qs-quant = { workspace = true }
```

Then run `uv lock` at the repository root.

```python
from qs_quant.metrics import (
    simple_returns,
    total_return,
    annualised_volatility,
    sharpe,
    max_drawdown,
    turnover,
    var_cvar,
)

values = [10_000, 9_900, 10_100, 10_300]  # floats, NumPy arrays or Decimals
r = simple_returns(values)
total_return(values)  # 0.03
annualised_volatility(r)  # None below 2 returns
var95, cvar95 = var_cvar(path_returns, alpha=0.95)  # needs at least 20 returns
```

| Function | Formula |
|---|---|
| `simple_returns(values)` | r_t = V_t / V_{t-1} - 1 |
| `total_return(values)` | V_T / V_0 - 1 |
| `annualised_volatility(returns, periods=252)` | std(r, ddof=1) * sqrt(periods) |
| `sharpe(returns, rf_annual=0.0, periods=252)` | mean(r - rf/periods) / std(r - rf/periods, ddof=1) * sqrt(periods) |
| `max_drawdown(values)` | max_t (1 - V_t / max_{s<=t} V_s), in [0, 1] |
| `turnover(fill_notionals, values)` | sum(abs(notional)) / mean(V) |
| `var_cvar(returns, alpha=0.95)` | q = quantile(R, 1 - alpha) (linear); VaR = -q; CVaR = -mean(R \| R <= q) |

## Conventions

- `values` is a value series V_0..V_T in time order; `returns` are simple returns
  (`simple_returns(values)` computes them).
- Annualisation uses 252 sessions per year (`periods`).
- VaR and CVaR are positive losses, and CVaR >= VaR. VaR is negative when even the
  `1 - alpha` quantile is a gain.
- Every result is a Python `float`. Store `qs_quant.__version__` next to stored results
  (C-NFR-09).

## Error contract

| Situation | Behaviour |
|---|---|
| Input not 1-D, contains NaN or infinity, or not numbers | `ValueError` naming the argument |
| `total_return`: empty, or V_0 <= 0 | `ValueError` |
| `total_return`: one value | `0.0` |
| `annualised_volatility`: fewer than 2 returns | `None` |
| `sharpe`: fewer than 2 returns, or all returns identical | `None` |
| `max_drawdown`: empty | `0.0` |
| `max_drawdown`: a value < 0, or V_0 <= 0 | `ValueError` |
| `simple_returns`: a value <= 0 | `ValueError` |
| `turnover`: no fills | `0.0` |
| `turnover`: empty values, or mean(V) <= 0 | `ValueError` |
| `var_cvar`: fewer than 20 returns | `ValueError("var_cvar needs at least 20 returns, got n")` |
| `var_cvar`: alpha not in (0, 1) | `ValueError` |
| `periods` <= 0, or `rf_annual` not finite | `ValueError` |

`None` means the metric is not defined for this series (the trading API lists it as
pending). `ValueError` means bad input (a service maps it to a 422).

## Calibration (K5)

Depend on `qs-quant[calibration]` (adds SciPy and statsmodels; the trading image does
not need them).

```python
from qs_quant.calibration import fit_gbm, fit_merton, fit_ou, log_returns, refusal_code

r = log_returns(prices)  # ln(S_t / S_{t-1})
gbm = fit_gbm(r)  # params: mu, sigma
ou = fit_ou(np.log(prices))  # params: kappa, theta, sigma (OU on log price)
merton = fit_merton(r)  # params: mu, sigma, lam, mu_j, sigma_j

if gbm.refused:
    code = refusal_code(gbm)  # e.g. "insufficient_history"
```

Every fit returns a `FitResult` (`model`, `params`, `std_errors`, `log_likelihood`,
`aic`, `n_obs`, `converged`, `refusal_reason`) and **never raises on bad data**. The
parameter names are those of Lane B's path generators, so a fit feeds a generator
directly. Store `qs_quant.__version__` and an input fingerprint with every fit (C-NFR-09).

| Model | Input | Minimum | Method | Standard errors |
|---|---|---|---|---|
| GBM | log returns | 60 | closed-form MLE | analytic |
| OU | log prices | 60 transitions | ADF (5%, AIC lags) then AR(1) OLS | delta method |
| Merton | log returns | 500 | L-BFGS-B, 3 starts, log-sum-exp, K = 10 jumps | numerical Hessian; NaN on a bound |

### Refusal codes

A refused fit has empty `params`, NaN `log_likelihood` and `aic`, `converged=False`, and
a `refusal_reason` of the form `"<code>: <sentence>"`:

| Code | When | Suggested HTTP |
|---|---|---|
| `invalid_input` | not 1-D, not numbers, NaN or infinity, bad `dt`, `n_starts` or `max_jumps` | 422 |
| `insufficient_history` | GBM or OU under 60, Merton under 500 observations | 422 `insufficient_history` |
| `constant_series` | the series does not move | 422 |
| `not_mean_reverting` | OU: ADF does not reject a unit root (the reason states the p-value), or the AR(1) slope is outside (0, 1) | 422 |
| `numerical_failure` | a non-finite estimate or a numerical error | 422 |

Evidence: the 50-replication recovery study, `docs/report/k5-recovery.md`, regenerated by
`uv run python -m studies.recovery_study`.

## Tests

```bash
cd libs/qs_quant
uv run ruff check . && uv run ruff format --check . && uv run mypy .
uv run pytest --cov=src
```

- Fixture values match an exact rational reference (`tests/reference.py`) to 1e-12
  (C-NFR-01).
- Properties on 200 generated series each: scale invariance, max drawdown in [0, 1],
  CVaR >= VaR, VaR rising with alpha, determinism (C-NFR-03, C-NFR-04).
- Each function runs in under 50 ms on 10,000 points (C-NFR-05).
- The library imports nothing that does I/O (C-NFR-07); the metrics import NumPy only.
  Coverage gate: 95% (C-NFR-08).
- Calibration: GBM and OU match exact rational references to 1e-12 (C-FR-01, C-FR-02);
  50 seeded random walks are refused and 50 OU series accepted at 90% or more; parameter
  recovery (50 replications for GBM and OU, 10 for Merton in CI); no input makes a fit
  raise (Hypothesis, C-FR-04); a Merton fit of 2,520 observations takes under 10 s
  (C-NFR-05).

## Changing this library

The K5 and K6 interfaces are frozen (contract change rule after J1). Changes are
additive only and approved by the consumers: Lane A (trading run metrics) for K6, Lane B
(calibration and Monte Carlo) for K5 and K6. A breaking change ships as a new function
name beside the old one.
