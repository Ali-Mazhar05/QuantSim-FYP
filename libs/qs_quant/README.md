# qs_quant

Pure quantitative maths shared by the QuantSim services: metrics and risk statistics
(K6, `qs_quant.metrics`) now, calibration (K5, `qs_quant.calibration`) next. No I/O, no
database, no network: NumPy only (SciPy and statsmodels arrive with K5). Formulas follow
the Lane C guide §7.6.

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
    simple_returns, total_return, annualised_volatility, sharpe,
    max_drawdown, turnover, var_cvar,
)

values = [10_000, 9_900, 10_100, 10_300]      # floats, NumPy arrays or Decimals
r = simple_returns(values)
total_return(values)                            # 0.03
annualised_volatility(r)                        # None below 2 returns
var95, cvar95 = var_cvar(path_returns, alpha=0.95)   # needs at least 20 returns
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
- The library imports nothing that does I/O (C-NFR-07). Coverage gate: 95% (C-NFR-08).

## Changing this library

K6's interface is frozen (contract change rule after J1). Changes are additive only and
approved by both consumers, Lane A (trading run metrics) and Lane B (Monte Carlo
VaR/CVaR). A breaking change ships as a new function name beside the old one.
