# K5 calibration: the mathematics and how each part is verified

`libs/qs_quant/src/qs_quant/calibration` (qs_quant 0.2.0). Lane C guide §7.1–7.5. Every
claim below names the test that checks it; the tests live in
`libs/qs_quant/tests/calibration/`.

**Notation.** Prices S_t at daily sessions, time step Δ = 1/252 years. Log returns
r_t = ln(S_t / S_{t−1}), t = 1..n. Log prices x_t = ln S_t. All parameters are annual.
log L is the log-likelihood, k the number of parameters, AIC = 2k − 2 log L
(Akaike 1974). SE means standard error.

---

## 1. Geometric Brownian motion

**Model.** dS = μ S dt + σ S dW. By Itô's lemma d ln S = (μ − σ²/2) dt + σ dW, so the
log returns are i.i.d.

  r_t ~ N((μ − σ²/2) Δ, σ² Δ).

**Likelihood.** With m = mean(r) and s² = (1/n) Σ (r_t − m)²,

  log L(μ, σ) = −(n/2) ln(2π σ²Δ) − Σ (r_t − (μ − σ²/2)Δ)² / (2σ²Δ).

**Estimator.** This is a Normal sample with mean ν = (μ − σ²/2)Δ and variance τ² = σ²Δ, whose
MLE is ν̂ = m, τ̂² = s² (ddof 0). Maximum likelihood is invariant under reparametrisation,
so

  σ̂ = s / √Δ,  μ̂ = m / Δ + σ̂²/2,  log L̂ = −(n/2) ln(2π s²) − n/2,  k = 2.

**Standard errors.** m and s² are independent, with var(m) = σ²Δ/n and var(s²) ≈ 2σ⁴Δ²/n.
By the delta method, se(σ̂) = σ̂/√(2n), and

  var(μ̂) = var(m)/Δ² + var(σ̂²)/4 = σ²/(nΔ) + σ⁴/(2n).

The code reports se(μ̂) = σ̂/√(nΔ), dropping the second term. Its relative size is σ²Δ/2,
about 8 × 10⁻⁵ for σ = 0.2, so the SE is understated by a factor √(1 + σ²Δ/2) − 1 ≈ 4 × 10⁻⁵.

**Refusals.** Fewer than 60 returns (`insufficient_history`); zero spread, tested
exactly (`constant_series`), because rounding in a mean can make a constant series show
a tiny non-zero variance and a meaningless σ̂.

**Verified by**
- `test_gbm.py::test_fit_matches_the_exact_closed_form`: μ̂, σ̂, both SEs, log L and AIC
  equal an exact rational computation (Python `Fraction`) to 1e-12.
- `test_maths.py::test_gbm_estimate_maximises_the_exact_likelihood_with_matching_errors`:
  - the reported log L is the exact likelihood at (μ̂, σ̂);
  - Nelder–Mead started elsewhere returns the same point (rel 1e-5);
  - se(σ̂) equals the inverse observed information from a numerical Hessian (rel 1e-4);
  - the Hessian's se(μ̂) equals √(σ²/(nΔ) + σ⁴/(2n)) (rel 1e-4), confirming the size of
    the neglected term.

---

## 2. Ornstein–Uhlenbeck on log price

**Model.** dX = κ(θ − X) dt + σ dW for X = ln S, where θ is the long-run log price. This is
the convention of Lane B's OU generator.

**Exact transition.** Solving the linear SDE over one step:

  X_{t+Δ} = θ + (X_t − θ) e^{−κΔ} + σ ∫_t^{t+Δ} e^{−κ(t+Δ−u)} dW_u.

So X_{t+Δ} | X_t is Normal with variance σ²(1 − e^{−2κΔ})/(2κ). This is exactly an AR(1):

  x_{t+1} = a + b x_t + e_t,  e_t ~ N(0, s²),
  b = e^{−κΔ},  a = θ(1 − b),  s² = σ²(1 − b²)/(2κ).

The map (κ, θ, σ) → (a, b, s) is one-to-one for κ > 0, i.e. b ∈ (0, 1).

**Estimator.** The conditional likelihood of x_1..x_n given x_0 is that of a Gaussian
linear regression. Its MLE is ordinary least squares for (a, b) with s² = RSS/n. The code
uses the centred form, b̂ = Sxy / Sxx and â = ȳ − b̂ x̄, which equals a generic
least-squares solve but loses less precision when b ≈ 1. By invariance:

  κ̂ = −ln b̂ / Δ,  θ̂ = â / (1 − b̂),  σ̂ = ŝ √(2κ̂ / (1 − b̂²)),
  log L̂ = −(n/2) ln(2π ŝ²) − n/2,  k = 3.

**Standard errors (delta method, and why it's exact here).** At the MLE the observed
information of (a, b, s) has three parts:
- the OLS block (XᵀX)/s², whose inverse is the familiar s²(XᵀX)⁻¹;
- 2n/s² for s;
- zero cross terms, because ∂² log L/∂(a, b)∂s ∝ Σ e_t (1, x_t) = 0 by the OLS normal
  equations.

So Σ = block-diag(s²(XᵀX)⁻¹, s²/(2n)). At a maximum the score is zero, so the information
under any smooth reparametrisation φ = g(a, b, s) transforms exactly as J⁻ᵀ I J⁻¹, and
J Σ Jᵀ *is* the inverse observed information of (κ, θ, σ), not just an approximation of
it. The Jacobian, with g(b) = 2κ/(1 − b²) so that σ = s√g:

  ∂κ/∂b = −1/(bΔ);  ∂θ/∂a = 1/(1 − b);  ∂θ/∂b = a/(1 − b)²;
  g′(b) = (2 ∂κ/∂b (1 − b²) + 4κb)/(1 − b²)²;  ∂σ/∂b = s g′/(2√g);  ∂σ/∂s = √g.

**Unit-root refusal.** A random walk has b = 1, but its estimate b̂ falls just *below* 1
(the Dickey–Fuller bias), so checking b̂ ∈ (0, 1) alone would accept random walks as mean
reverting. The fit therefore runs the augmented Dickey–Fuller test first:
- the regression is Δx_t = α + γ x_{t−1} + Σ δ_j Δx_{t−j} + ε_t, with the lag order chosen
  by AIC;
- H₀ is γ = 0 (a unit root), with MacKinnon (1994) p-values from statsmodels;
- the series is refused unless p < 0.05, and the reason states p.

b̂ ∉ (0, 1) is then refused too, for example an alternating series with b̂ < 0. Both carry
the `not_mean_reverting` code. statsmodels 0.15 is called with `result_object=True`,
since without it a FutureWarning fires.

**Known finite-sample bias.** κ̂ is biased upward in finite samples, a standard result for
this estimator (Tang and Chen 2009). In the study, the mean κ̂ is 5.53 against a true 5
over 10 years, +0.50 SE: inside the guide's bar, so the reported SE stays honest. No bias
correction is applied, which keeps the fit equal to the MLE that the SEs describe.

**Verified by**
- `test_ou.py::test_fit_matches_exact_ols_and_the_transform`: (κ̂, θ̂, σ̂), log L and AIC
  from exact rational OLS, to 1e-12.
- `test_ou.py::test_the_jacobian_matches_central_differences`: the analytic Jacobian vs a
  numerical one (rel 1e-6).
- `test_maths.py::test_ou_ols_route_is_the_exact_maximum_likelihood_estimate`: the
  reported log L equals the exact OU transition likelihood at the estimate (rel 1e-10),
  and Nelder–Mead on that density from a distant start reaches the OLS estimate
  (rel 1e-5).
- `test_maths.py::test_ou_delta_method_errors_equal_the_inverse_observed_information`: the
  delta-method SEs equal the numerical inverse observed information of the exact density
  (rel 1e-3).
- `test_ou.py`: 50 seeded random walks are refused in ≥ 90% (observed 46/50) and 50 OU
  series are accepted in ≥ 90% (observed 50/50, guide §14); a negative-slope series is
  refused; every ADF refusal states its p-value.

---

## 3. Merton jump diffusion

**Model.** dS/S = (μ − λk̄) dt + σ dW + (e^Y − 1) dN, where N is Poisson with rate λ and
the jump log-sizes are Y ~ N(μ_J, σ_J²). The compensator k̄ = E[e^Y − 1] = e^{μ_J + σ_J²/2} − 1
makes E[S_{t+Δ}/S_t] = e^{μΔ}, so μ keeps its meaning as the expected rate of return.
This matches Lane B's Merton generator.

**One step.** Conditional on j jumps in a step, the log return is Gaussian:

  r | N = j ~ N((μ − σ²/2 − λk̄)Δ + j μ_J,  σ²Δ + j σ_J²),
  P(N = j) = e^{−λΔ}(λΔ)^j / j!.

So r has the Poisson mixture density (Press 1967)

  f(r) = Σ_{j=0}^{∞} P(N = j) φ(r; mean_j, var_j).

**Truncation.** The sum stops at K = 10 jumps per step. The dropped mass is
P(N > 10) ≈ (λΔ)¹¹/11!, about 10⁻²³ for λ = 10, and still only about 10⁻⁸ at λ = 252,
the upper bound, where λΔ = 1.

**Numerics.** ln f is computed as logsumexp_j(ln P(N = j) + ln φ_j), so no term under- or
overflows. λ = 0 is exact: only j = 0 carries weight, and the model reduces to GBM. A
non-finite likelihood returns a 10³⁰⁰ penalty, so the optimiser backs off instead of
failing. Floating-point warnings are silenced only inside this objective (`np.errstate`,
local to the call).

**Estimator.** The likelihood is maximised with L-BFGS-B within these bounds:

| Parameter | Lower | Upper |
|---|---|---|
| μ | −2 | 2 |
| σ | 10⁻⁴ | 3 |
| λ | 0 | 252 |
| μ_J | −1 | 1 |
| σ_J | 10⁻⁴ | 1 |

There are three starts:
1. λ = 1, μ_J = 0, σ_J = 0.02;
2. λ = 5, μ_J = −0.05, σ_J = 0.05;
3. λ = 20, μ_J = 0, σ_J = 0.02.

Each starts from the GBM fit's μ and σ. The best log L is kept, and `converged` is the
optimiser's flag at that start. The likelihood surface can have several local maxima
(few large jumps vs many small ones), which is why the starts differ in λ. Fewer than
500 returns are refused, because short windows are unstable.

**Standard errors.** Inverse of the central-difference Hessian of −log L at the optimum:
- steps are 10⁻⁴·max(1, |θ_i|), shrunk to stay inside the bounds;
- a parameter within 10⁻⁶ of a bound is not an interior maximum, so its SE is NaN and it
  is left out of the Hessian;
- if the remaining Hessian is not positive definite (Cholesky fails), their SEs are NaN
  and the estimate is still returned.

**Moments.** These are used to check the density:
- E[r] = (μ − σ²/2 − λk̄)Δ + λΔ μ_J;
- Var[r] = σ²Δ + λΔ(σ_J² + μ_J²), the variance of the diffusion plus that of a compound
  Poisson sum.

**Identification notes.**
- μ is weakly identified, as in GBM: its SE is about σ/√T. It shows up as a large SE, not
  as bias.
- At 10 years of data (n = 2,520), 40 fits gave standardised errors (estimate − true)/SE
  with spread 0.83–1.11 and 92–95% coverage at ±2 SE, so the SEs are calibrated.
- σ_J is the weakest: mean z −0.31 and spread 1.11, so its SE is about 10% optimistic at
  that length. At n = 5,000 its coverage is 98%.

**Verified by**
- `test_maths.py::test_merton_density_integrates_to_one_with_the_analytic_moments`: the
  truncated density integrates to 1 (rel 1e-9), and its numerically integrated mean and
  variance equal the analytic moments above (rel 1e-7).
- `test_merton.py::test_the_objective_handles_no_jumps_and_penalises_the_impossible`:
  λ = 0 equals the GBM Gaussian likelihood (rel 1e-12); an impossible point (σ = 0)
  returns the penalty.
- `test_maths.py::test_merton_fit_is_a_local_maximum`: one SE either way along any
  parameter lowers log L.
- `test_merton.py`: bound handling (NaN SE on a bound, NaN for a non-positive-definite
  Hessian), n = 499 refused and n = 500 accepted, ±50% days stay finite (C-NFR-02),
  determinism.
- `test_robustness.py`: a 2,520-observation fit takes under 10 s (about 3 s here,
  C-NFR-05).

---

## 4. Parameter recovery (guide §7.5)

For each model, 50 samples are simulated with known parameters and fitted. Per
parameter the study reports:
- **coverage:** the share of samples whose true value lies within ±2 SE; the bar is 85%
  (80% for λ and σ_J);
- **standardised bias:** mean(est − true)/mean(SE); the bar is below 1 in absolute value.

All ten parameters pass; the full table is `docs/report/k5-recovery.md`, generated by
`libs/qs_quant/studies/recovery_study.py`.

| Parameter | Coverage | Standardised bias |
|---|---|---|
| GBM μ, σ | 98%, 96% | +0.10, −0.08 |
| OU κ, θ, σ | 92%, 90%, 92% | +0.50, −0.11, +0.13 |
| Merton μ, σ, λ, μ_J, σ_J | 100%, 96%, 98%, 96%, 98% | +0.13, +0.06, −0.10, −0.11, −0.17 |

CI (`test_recovery.py`) runs the same seeded streams: all 50 for GBM and OU, and the
first 10 for Merton (a coarse regression guard, since one Merton fit takes seconds).

---

## 5. End to end, as Lane B uses it (`test_e2e.py`)

**Real data.** The input is `contracts/fixtures/replay_ticks_2020.json`: Lane B's C3
fixture of real 2020 Tiingo prices through the real ingestion pipeline, as
`market.tick.v1` ticks with Decimal closes. It goes Decimal closes → `log_returns` →
fit → JSON, as B15 stores it.

| Name | GBM σ̂ | K6 volatility (simple returns) | OU | Merton |
|---|---|---|---|---|
| AAPL | 0.466 | 0.467 | refused, ADF p = 0.92 | refused, 252 < 500 |
| KO | 0.348 | 0.347 | refused, ADF p = 0.15 | refused |
| MSFT | 0.440 | 0.439 | refused, ADF p = 0.55 | refused |
| NVDA | 0.581 | 0.579 | refused, ADF p = 0.76 | refused |
| TSLA | 0.895 | 0.895 | refused, ADF p = 0.85 | refused |

The tests assert:
- σ̂ equals the annualised standard deviation of the log returns exactly;
- σ̂ agrees with K6's independent volatility within 1%;
- the values match what the market did in 2020 (AAPL about 47%, TSLA about 90%, KO the
  calmest);
- real share prices are refused for OU, which is the case the ADF refusal exists for;
- a single year is too short for Merton.

**Synthetic fixture.** The 60-step synthetic C3 run has 59 returns, so every path is
refused with `insufficient_history: … got 59`. That is Lane B's 422 path.

**Calibrate, simulate, recalibrate.** This is the B15 → B16 hand-off. Each model is fitted
once, paths are simulated with the fitted parameters using the same step formulas as Lane
B's generators, and each path is fitted again:
- GBM (fitted on AAPL 2020) and OU: 40 paths each, coverage ≥ 85%;
- Merton: 8 paths, every refit converges, and at least 6 of 8 lie within ±2 SE for every
  parameter.

**Storage determinism.** The same window gives the byte-identical stored JSON, which B15's
input fingerprint relies on (C-NFR-03).

---

## 6. Robustness and purity

- No input makes a fit raise (C-FR-04). Hypothesis feeds arbitrary floats (NaN, ±∞,
  ±10³⁰⁸, empty, up to 600 values) to all three fits. Every call returns a `FitResult`,
  and every refusal has a known code: `invalid_input`, `insufficient_history`,
  `constant_series`, `not_mean_reverting` or `numerical_failure`.
- Determinism: same input, identical result. There is no randomness in any fit.
- The library does no I/O (C-NFR-07). `qs_quant.metrics` imports NumPy only, so the trading
  image never needs SciPy. Calibration needs the `qs-quant[calibration]` extra.

## 7. Limitations

- OU κ̂ carries the usual small-sample upward bias (+0.5 SE over 10 years); it is reported,
  not corrected.
- Merton σ_J's SE is about 10% optimistic at 10 years of data; prefer longer windows when
  jump-size uncertainty matters.
- A Merton parameter on a bound has no SE (NaN). B15 must store NaN as null, since JSON
  has no NaN.
- The ADF test decides at 5%. A genuinely mean-reverting but slow series (half-life of
  years) over a short window can be refused, which is the conservative choice the guide
  asks for.

## References

- Akaike, H. (1974). A new look at the statistical model identification. *IEEE Trans.
  Automatic Control* 19(6).
- Campbell, J., Lo, A. and MacKinlay, C. (1997). *The Econometrics of Financial Markets*,
  ch. 9.
- Dickey, D. and Fuller, W. (1979). Distribution of the estimators for autoregressive time
  series with a unit root. *JASA* 74.
- MacKinnon, J. (1994). Approximate asymptotic distribution functions for unit-root and
  cointegration tests. *J. Business and Economic Statistics* 12.
- Merton, R. (1976). Option pricing when underlying stock returns are discontinuous.
  *J. Financial Economics* 3.
- Press, S. J. (1967). A compound events model for security prices. *J. Business* 40.
- Tang, C. Y. and Chen, S. X. (2009). Parameter estimation and bias correction for
  diffusion processes. *J. Econometrics* 149.
- Vasicek, O. (1977). An equilibrium characterization of the term structure. *J. Financial
  Economics* 5.
