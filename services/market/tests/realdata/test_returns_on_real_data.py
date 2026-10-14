"""Returns and volatility on real bars (FR-MKT-003), against independent implementations.

numpy and pandas are used on purpose: they do not share a line of code with
``qs_market.returns``, so agreement is evidence and not an echo.
"""

import math

import numpy as np
import pandas as pd
import pytest

from qs_market import cleaning, returns

pytestmark = pytest.mark.realdata

SPLIT_DAYS = {"NVDA": {"2021-07-20", "2024-06-10"}, "TSLA": {"2020-08-31", "2022-08-25"}}


def test_log_returns_equal_an_independent_computation(
    gated: dict[str, cleaning.GateResult],
    series: dict[str, list[returns.ReturnPoint]],
    symbol: str,
) -> None:
    out = series[symbol]
    adj = np.array([float(b.adj_close or b.close) for b in gated[symbol].clean])
    raw = np.array([float(b.close) for b in gated[symbol].clean])
    assert out[0].log_return is None and out[0].adj_log_return is None
    assert np.allclose(np.diff(np.log(adj)), [p.adj_log_return for p in out[1:]], atol=1e-12)
    assert np.allclose(np.diff(np.log(raw)), [p.log_return for p in out[1:]], atol=1e-12)


@pytest.mark.parametrize(("length", "attribute"), [(20, "vol_20d"), (60, "vol_60d")])
def test_volatility_equals_pandas_rolling_std(
    gated: dict[str, cleaning.GateResult],
    series: dict[str, list[returns.ReturnPoint]],
    symbol: str,
    length: int,
    attribute: str,
) -> None:
    out = series[symbol]
    adj = np.array([float(b.adj_close or b.close) for b in gated[symbol].clean])
    expected = pd.Series(np.diff(np.log(adj))).rolling(length).std(ddof=1) * math.sqrt(252)
    mine = np.array(
        [getattr(p, attribute) if getattr(p, attribute) is not None else np.nan for p in out[1:]]
    )
    assert np.array_equal(np.isnan(mine), np.isnan(expected.to_numpy())), (
        "volatility is defined on different rows than the rolling window"
    )
    defined = ~np.isnan(mine)
    assert defined.any()
    assert np.allclose(mine[defined], expected.to_numpy()[defined], atol=1e-9)


def test_a_split_does_not_look_like_a_crash_in_adjusted_returns(
    series: dict[str, list[returns.ReturnPoint]], symbol: str
) -> None:
    out = {p.session_date.isoformat(): p for p in series[symbol]}
    for day in SPLIT_DAYS.get(symbol, set()):
        point = out[day]
        assert point.log_return is not None and point.adj_log_return is not None
        assert point.log_return < -1.0, f"{symbol} {day}: the raw series should show the drop"
        assert abs(point.adj_log_return) < 0.5, (
            f"{symbol} {day}: adjusted return {point.adj_log_return} still looks like a crash"
        )


def test_volatility_is_in_a_plausible_range(
    series: dict[str, list[returns.ReturnPoint]], symbol: str
) -> None:
    vols = [p.vol_20d for p in series[symbol] if p.vol_20d is not None]
    assert vols and min(vols) > 0.0
    assert max(vols) < 3.0, f"{symbol}: annualised 20 day volatility above 300 percent"
