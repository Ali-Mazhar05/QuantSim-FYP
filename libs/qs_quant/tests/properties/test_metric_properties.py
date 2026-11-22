"""K6 properties on 200 generated series each (C-FR-05/06, C-NFR-03/04)."""

import math

import numpy as np
from hypothesis import assume, given
from hypothesis import strategies as st

from qs_quant.metrics import (
    annualised_volatility,
    max_drawdown,
    sharpe,
    simple_returns,
    total_return,
    turnover,
    var_cvar,
)
from tests import reference as ref

values_st = st.lists(
    st.floats(min_value=1.0, max_value=1e6, allow_nan=False, allow_infinity=False),
    min_size=3,
    max_size=300,
)
returns_st = st.lists(
    st.floats(min_value=-0.5, max_value=0.5, allow_nan=False, allow_infinity=False),
    min_size=20,
    max_size=500,
)
alpha_st = st.floats(min_value=0.8, max_value=0.99)

Metrics = tuple[float | None, ...]


def all_metrics(values: list[float], fills: list[float]) -> Metrics:
    r = simple_returns(values)
    return (
        total_return(values),
        annualised_volatility(r),
        sharpe(r),
        max_drawdown(values),
        turnover(fills, values),
    )


def near(a: float | None, b: float | None, tol: float) -> bool:
    if a is None or b is None:
        return a is b
    return math.isclose(a, b, rel_tol=tol, abs_tol=tol)


@given(values_st)
def test_scaling_by_a_power_of_two_is_bit_identical(values: list[float]) -> None:
    # x8 is exact in binary floating point, so every ratio, sum and mean scales exactly:
    # any difference means a formula is not truly scale-free
    fills = values[:3]
    assert all_metrics(values, fills) == all_metrics(
        [v * 8 for v in values], [f * 8 for f in fills]
    )


@given(values_st)
def test_scaling_by_ten_is_invariant_within_rounding(values: list[float]) -> None:
    # The guide's wording (x10). x10 is not exact in binary, and a return near 0 or a
    # near-constant series turns 1e-16 rounding into a large relative error, so compare
    # with a mixed tolerance on series with real dispersion
    assume(float(np.ptp(simple_returns(values))) > 1e-3)
    fills = values[:3]
    base = all_metrics(values, fills)
    scaled = all_metrics([v * 10 for v in values], [f * 10 for f in fills])
    assert all(near(a, b, 1e-9) for a, b in zip(base, scaled, strict=True))


@given(st.lists(st.integers(min_value=1, max_value=10_000), min_size=3, max_size=60))
def test_agrees_with_the_exact_reference(ints: list[int]) -> None:
    # Integer cent values keep the fractions small enough to stay fast
    values = [i / 100 for i in ints]
    exact = [ref.F(i) / 100 for i in ints]
    assume(float(np.ptp(simple_returns(values))) > 1e-3)
    r, er = simple_returns(values), ref.returns(exact)
    assert near(total_return(values), float(ref.total_return(exact)), 1e-9)
    assert near(annualised_volatility(r), ref.volatility(er), 1e-9)
    assert near(sharpe(r), ref.sharpe(er), 1e-9)
    assert near(max_drawdown(values), float(ref.max_drawdown(exact)), 1e-9)


@given(values_st)
def test_max_drawdown_is_in_unit_interval_and_zero_when_sorted(values: list[float]) -> None:
    assert 0.0 <= max_drawdown(values) <= 1.0
    assert max_drawdown(sorted(values)) == 0.0


@given(values_st)
def test_volatility_and_turnover_are_never_negative(values: list[float]) -> None:
    vol = annualised_volatility(simple_returns(values))
    assert vol is None or vol >= 0.0
    assert turnover([-v for v in values[:3]], values) >= 0.0


@given(returns_st, alpha_st)
def test_cvar_is_at_least_var(returns: list[float], alpha: float) -> None:
    var, cvar = var_cvar(returns, alpha)
    assert cvar >= var


@given(returns_st)
def test_var_grows_with_confidence(returns: list[float]) -> None:
    assert var_cvar(returns, 0.99)[0] >= var_cvar(returns, 0.95)[0]


@given(values_st, returns_st)
def test_every_metric_is_deterministic(values: list[float], returns: list[float]) -> None:
    fills = values[:3]
    assert all_metrics(values, fills) == all_metrics(values, fills)
    assert var_cvar(returns) == var_cvar(returns)
