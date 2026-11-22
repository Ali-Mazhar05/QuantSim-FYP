"""End to end, the way Lane B uses K5.

B15 (calibration job): prices arrive in the ``market.tick.v1`` contract shape, with
closes as Decimal strings; the job takes log returns, fits, and stores the result (JSON)
or returns a 422 refusal. B16 (Monte Carlo) then simulates paths with the fitted
parameters. These tests run that chain on the repository's contract fixtures, which
Lane B's feeds serve:

- ``contracts/fixtures/replay_ticks_2020.json``: real 2020 daily prices of five names,
  recorded from Tiingo through the real ingestion pipeline (C3);
- ``contracts/fixtures/synthetic_ticks.json``: a 60-step synthetic run (C3);

and close the loop: calibrate on real prices, simulate with the fitted parameters using
the same step formulas as Lane B's generators, and recalibrate on the simulated paths.
"""

import dataclasses
import json
import math
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Any

import numpy as np

from qs_quant.calibration import FitResult, fit_gbm, fit_merton, fit_ou, log_returns, refusal_code
from qs_quant.metrics import annualised_volatility, simple_returns
from tests.calibration import simulate as sim

REPO = Path(__file__).resolve().parents[4]
REPLAY = REPO / "contracts" / "fixtures" / "replay_ticks_2020.json"
SYNTHETIC = REPO / "contracts" / "fixtures" / "synthetic_ticks.json"
NAMES = ("AAPL", "KO", "MSFT", "NVDA", "TSLA")


def load(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        data: dict[str, Any] = json.load(handle)
    return data


def closes_by_symbol(ticks: list[dict[str, Any]]) -> dict[str, list[Decimal]]:
    """Closes per symbol in seq order, as Decimals, the way a consumer pages the feed."""
    out: dict[str, list[Decimal]] = defaultdict(list)
    for tick in sorted(ticks, key=lambda t: t["seq"]):
        out[tick["symbol"]].append(Decimal(tick["close"]))
    return dict(out)


def stored(fit: FitResult) -> str:
    """The fit as B15 stores it (JSON). NaN is not JSON, so this fails on a NaN estimate."""
    return json.dumps(dataclasses.asdict(fit), sort_keys=True, allow_nan=False)


REAL = closes_by_symbol(load(REPLAY)["items"])


def test_the_replay_fixture_is_a_full_2020_year_of_five_names() -> None:
    assert set(REAL) == set(NAMES)
    assert all(len(closes) == 253 for closes in REAL.values())


def test_real_2020_prices_calibrate_gbm_as_b15_would() -> None:
    for name in NAMES:
        r = log_returns(REAL[name])  # Decimal closes in, float log returns out
        fit = fit_gbm(r)
        assert fit.refusal_reason is None, name
        assert fit.n_obs == 252
        # sigma is the annualised standard deviation of the log returns (MLE, ddof 0)
        expected_sigma = float(np.std(r)) * math.sqrt(252)
        assert math.isclose(fit.params["sigma"], expected_sigma, rel_tol=1e-12), name
        # and agrees with K6's volatility of simple returns to within 1% (different
        # return definition and ddof), so the two libraries tell one story
        k6 = annualised_volatility(simple_returns(REAL[name]))
        assert k6 is not None
        assert math.isclose(fit.params["sigma"], k6, rel_tol=0.01), name
        # Storable as JSON and back without loss
        assert json.loads(stored(fit))["params"] == fit.params


def test_real_2020_volatility_is_what_the_market_did() -> None:
    sigma = {name: fit_gbm(log_returns(REAL[name])).params["sigma"] for name in NAMES}
    # 2020 realised volatility: AAPL about 47%, TSLA about 90%, KO the calmest of the five
    assert 0.40 < sigma["AAPL"] < 0.55
    assert 0.80 < sigma["TSLA"] < 1.00
    assert min(sigma, key=lambda k: sigma[k]) == "KO"


def test_real_share_prices_are_refused_as_not_mean_reverting() -> None:
    # Log share prices behave like random walks: OU must be refused with the ADF p-value,
    # which B15 returns as a 422 instead of simulating behaviour the data cannot show
    for name in NAMES:
        fit = fit_ou(np.log([float(c) for c in REAL[name]]))
        assert refusal_code(fit) == "not_mean_reverting", name
        assert fit.refusal_reason is not None and "ADF p = " in fit.refusal_reason


def test_one_year_is_too_short_for_merton() -> None:
    fit = fit_merton(log_returns(REAL["AAPL"]))
    assert refusal_code(fit) == "insufficient_history"
    assert (
        fit.refusal_reason
        == "insufficient_history: Merton needs at least 500 observations, got 252"
    )


def test_the_synthetic_fixture_is_one_return_short_of_a_gbm_fit() -> None:
    data = load(SYNTHETIC)
    for path in data["paths"]:
        for name, closes in closes_by_symbol(path["items"]).items():
            fit = fit_gbm(log_returns(closes))
            assert (
                fit.refusal_reason
                == "insufficient_history: GBM needs at least 60 observations, got 59"
            ), name


def test_calibrate_simulate_recalibrate_gbm() -> None:
    # B15 fits AAPL 2020; B16 simulates ten-year paths with those parameters; fitting each
    # path again must recover them (true value within +-2 SE in at least 85% of paths)
    fitted = fit_gbm(log_returns(REAL["AAPL"])).params
    refits = [
        fit_gbm(sim.gbm_log_returns(sim.rng("e2e-gbm", path), 2_520, **fitted))
        for path in range(40)
    ]
    assert all(not f.refused for f in refits)
    for name, true in fitted.items():
        covered = np.mean([abs(f.params[name] - true) <= 2 * f.std_errors[name] for f in refits])
        assert covered >= 0.85, (name, covered)


def test_calibrate_simulate_recalibrate_ou() -> None:
    # A mean-reverting series is fitted, simulated with the fit and fitted again
    source = sim.ou_log_prices(sim.rng("e2e-ou-source", 0), 2_520, **sim.OU_TRUE)
    fitted = fit_ou(source).params
    refits = [
        fit_ou(sim.ou_log_prices(sim.rng("e2e-ou", path), 2_520, **fitted)) for path in range(40)
    ]
    accepted = [f for f in refits if not f.refused]
    assert len(accepted) >= 36  # 90%
    for name, true in fitted.items():
        covered = np.mean([abs(f.params[name] - true) <= 2 * f.std_errors[name] for f in accepted])
        assert covered >= 0.85, (name, covered)


def test_calibrate_simulate_recalibrate_merton() -> None:
    # Fit a ten-year jump-diffusion sample, simulate eight ten-year paths with the fit and
    # fit each again: every refit converges, and for every parameter at least 6 of the 8
    # land within +-2 SE of the value they were simulated from. (At this length the
    # standard errors are calibrated: over 40 fits the standardised errors have a spread
    # of 0.83-1.11 and 92-95% coverage; see docs/report/k5-maths.md. Asking every
    # estimate to land within 3 SE would fail by chance about once in 20 runs.)
    source = sim.merton_log_returns(sim.rng("e2e-merton-source", 0), 2_520, **sim.MERTON_TRUE)
    first = fit_merton(source)
    assert first.refusal_reason is None
    refits = [
        fit_merton(sim.merton_log_returns(sim.rng("e2e-merton", path), 2_520, **first.params))
        for path in range(8)
    ]
    assert all(f.refusal_reason is None and f.converged for f in refits)
    for name, true in first.params.items():
        within = sum(abs(f.params[name] - true) <= 2 * f.std_errors[name] for f in refits)
        assert within >= 6, (name, within)


def test_the_same_window_stores_the_same_result() -> None:
    # C-NFR-03 at the storage boundary: B15's input fingerprint is only meaningful if the
    # same window always gives the same stored row
    closes = REAL["MSFT"]
    assert stored(fit_gbm(log_returns(closes))) == stored(fit_gbm(log_returns(list(closes))))
