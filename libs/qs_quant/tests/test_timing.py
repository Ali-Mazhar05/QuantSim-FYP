"""C-NFR-05: each K6 function under 50 ms for 10,000 points."""

import timeit
from collections.abc import Callable

import numpy as np
import pytest
from numpy.typing import NDArray

from qs_quant.metrics import (
    annualised_volatility,
    max_drawdown,
    sharpe,
    simple_returns,
    total_return,
    turnover,
    var_cvar,
)

Case = tuple[str, Callable[[NDArray[np.float64]], object]]
CASES: list[Case] = [
    ("total_return", total_return),
    ("annualised_volatility", lambda v: annualised_volatility(simple_returns(v))),
    ("sharpe", lambda v: sharpe(simple_returns(v))),
    ("max_drawdown", max_drawdown),
    ("turnover", lambda v: turnover(v[:1000], v)),
    ("var_cvar", lambda v: var_cvar(simple_returns(v))),
]


@pytest.mark.parametrize(("name", "fn"), CASES, ids=[c[0] for c in CASES])
def test_under_50_ms_for_10k_points(name: str, fn: Callable[[NDArray[np.float64]], object]) -> None:
    rng = np.random.default_rng(7)
    values = 100.0 * np.cumprod(1.0 + rng.normal(0.0, 0.01, 10_000))
    # Best of five keeps the check stable on a busy CI agent
    best = min(timeit.repeat(lambda: fn(values), number=1, repeat=5))
    assert best < 0.050, f"{name} took {best * 1000:.1f} ms"
