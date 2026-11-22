"""C-FR-04: no input makes a fit raise; every call returns a FitResult, and a refusal
always carries a known code."""

import math
import time

import numpy as np
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from qs_quant.calibration import (
    REFUSAL_CODES,
    FitResult,
    fit_gbm,
    fit_merton,
    fit_ou,
    log_returns,
    refusal_code,
)
from tests.calibration import simulate as sim

any_floats = st.floats(allow_nan=True, allow_infinity=True, width=64)
series = st.lists(any_floats, min_size=0, max_size=400)


def well_formed(fit: FitResult) -> bool:
    if fit.refused:
        return refusal_code(fit) in REFUSAL_CODES and fit.params == {}
    return math.isfinite(fit.log_likelihood) and all(math.isfinite(v) for v in fit.params.values())


@given(series)
def test_gbm_never_raises(values: list[float]) -> None:
    assert well_formed(fit_gbm(values))


@given(series)
def test_ou_never_raises(values: list[float]) -> None:
    assert well_formed(fit_ou(values))


# 500 points is the smallest input that reaches the optimiser, so the large-example
# health check is expected here
@settings(
    max_examples=15, suppress_health_check=[HealthCheck.large_base_example, HealthCheck.too_slow]
)
@given(st.lists(any_floats, min_size=500, max_size=600))
def test_merton_never_raises(values: list[float]) -> None:
    assert well_formed(fit_merton(values, n_starts=1))


@settings(max_examples=50)
@given(st.lists(st.floats(min_value=-1e6, max_value=1e6), min_size=60, max_size=300))
def test_finite_but_wild_returns_give_a_fit_or_a_refusal(values: list[float]) -> None:
    assert well_formed(fit_gbm(values))
    assert well_formed(fit_ou(values))


def test_log_returns_of_prices() -> None:
    assert np.allclose(log_returns([100.0, 110.0, 99.0]), [math.log(1.1), math.log(0.9)])
    assert log_returns([100.0]).size == 0


def test_merton_fits_ten_years_in_under_ten_seconds() -> None:
    # C-NFR-05
    r = sim.merton_log_returns(np.random.default_rng(9), 2_520, **sim.MERTON_TRUE)
    start = time.perf_counter()
    fit = fit_merton(r)
    elapsed = time.perf_counter() - start
    assert not fit.refused
    assert elapsed < 10.0, f"Merton took {elapsed:.1f} s"
