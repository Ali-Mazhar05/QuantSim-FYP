"""K6 VaR and CVaR against the exact reference and the error contract (C-FR-06)."""

import math
from fractions import Fraction

import pytest

from qs_quant.metrics import MIN_RETURNS, simple_returns, var_cvar
from tests import reference as ref
from tests.test_performance import EXACT_VALUES, VALUES


@pytest.mark.parametrize("alpha", ["0.95", "0.99", "0.9"])
def test_var_cvar_match_exact(alpha: str) -> None:
    var, cvar = var_cvar(simple_returns(VALUES), float(alpha))
    exact_var, exact_cvar = ref.var_cvar(ref.returns(EXACT_VALUES), Fraction(alpha))
    assert math.isclose(var, float(exact_var), rel_tol=1e-12)
    assert math.isclose(cvar, float(exact_cvar), rel_tol=1e-12)
    assert cvar >= var


def test_fewer_than_twenty_returns_is_refused() -> None:
    with pytest.raises(ValueError, match="at least 20 returns, got 19"):
        var_cvar([0.01] * (MIN_RETURNS - 1))


@pytest.mark.parametrize("alpha", [0.0, 1.0, 1.5, -0.1])
def test_alpha_outside_open_unit_interval_is_refused(alpha: float) -> None:
    with pytest.raises(ValueError, match="alpha"):
        var_cvar([0.01] * MIN_RETURNS, alpha)


def test_var_is_negative_when_the_tail_is_a_gain() -> None:
    var, cvar = var_cvar([0.01 * (i + 1) for i in range(MIN_RETURNS)])
    assert var < 0
    assert cvar >= var


def test_results_are_python_floats() -> None:
    var, cvar = var_cvar(simple_returns(VALUES))
    assert type(var) is float
    assert type(cvar) is float
