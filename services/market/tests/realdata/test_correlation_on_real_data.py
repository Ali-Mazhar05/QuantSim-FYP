"""Correlation matrices on eleven years of real bars for the six corpus symbols: every
cell equals pandas on the vendor adjusted closes (computed here without qs_market), the
2024 NVDA split is not a crash, and a full basket over 40 rolling windows is fast."""

import os
import time
from datetime import date
from typing import Any

import httpx
import numpy as np
import pandas as pd
import pytest

from qs_template import Database
from qs_template.auth import Role
from tests import read_support as support
from tests.instrument_support import API, bearer, make_token
from tests.read_support import add_instrument, ingest

from .conftest import SYMBOLS, Records
from .test_read_api_on_real_data import RecordedSource

client = support.client
database = support.database
pytestmark = [pytest.mark.realdata, pytest.mark.db]

SECONDS = float(os.environ.get("QS_REALDATA_CORRELATION_SECONDS", "2"))


@pytest.fixture
async def basket(database: Database, corpus: dict[str, Records]) -> None:
    for symbol in SYMBOLS:
        dates = [date.fromisoformat(r["date"]) for r in corpus[symbol]]
        new_id = await add_instrument(database, symbol)
        await ingest(database, RecordedSource(corpus), [new_id], (min(dates), max(dates)))


async def correlations(http: httpx.AsyncClient, body: dict[str, Any]) -> Any:
    response = await http.post(
        f"{API}/correlations", json=body, headers=bearer(make_token(Role.VIEWER))
    )
    assert response.status_code == 200, response.text
    return response.json()


def vendor_returns(corpus: dict[str, Records]) -> pd.DataFrame:
    """Adjusted log returns straight from the vendor records, one column per symbol."""
    columns = {}
    for symbol, records in corpus.items():
        closes = pd.Series(
            {r["date"][:10]: float(r["adj_close"]) for r in records}, dtype=float
        ).sort_index()
        columns[symbol] = np.log(closes).diff()
    return pd.DataFrame(columns)


def check_window(window: dict[str, Any], returns: pd.DataFrame) -> None:
    inside = returns[(returns.index >= window["start"]) & (returns.index <= window["end"])]
    inside = inside.dropna()
    symbols = window["symbols"]
    assert window["n_obs"] == len(inside)
    expected = inside[symbols].corr().to_numpy()
    got = np.array([[float(v) for v in row] for row in window["matrix"]])
    assert np.allclose(got, expected, atol=2e-8, rtol=0), window["start"]


async def test_every_cell_equals_pandas_on_the_vendor_adjusted_closes(
    client: httpx.AsyncClient, basket: None, corpus: dict[str, Records]
) -> None:
    returns = vendor_returns(corpus)
    years = [{"start": f"{y}-01-01", "end": f"{y}-12-31"} for y in (2020, 2021, 2022, 2023)]
    rolling = {"length": 60, "step": 20, "start": "2022-01-01", "end": "2024-06-28"}

    yearly = await correlations(client, {"symbols": list(SYMBOLS), "windows": years})
    assert [w["start"] for w in yearly["windows"]] == [y["start"] for y in years]
    for window in yearly["windows"]:
        assert window["symbols"] == sorted(SYMBOLS)
        assert window["n_obs"] > 240
        check_window(window, returns)

    sliding = await correlations(client, {"symbols": list(SYMBOLS), "rolling": rolling})
    assert len(sliding["windows"]) > 20
    assert all(w["n_obs"] == 60 for w in sliding["windows"])
    for window in sliding["windows"]:
        check_window(window, returns)

    again = await correlations(client, {"symbols": list(reversed(SYMBOLS)), "windows": years})
    assert again == yearly


async def test_the_nvda_split_window_is_not_a_crash(
    client: httpx.AsyncClient, basket: None, corpus: dict[str, Records]
) -> None:
    window = {"start": "2024-05-20", "end": "2024-06-28"}
    body = await correlations(
        client, {"symbols": ["NVDA", "AAPL", "SPY"], "windows": [window], "min_observations": 10}
    )
    [result] = body["windows"]
    cells = [v for row in result["matrix"] for v in row]
    assert None not in cells
    assert all("nan" not in v.lower() for v in cells)
    check_window(result, vendor_returns(corpus))
    # a split read as a 90 percent fall would pull NVDA against the market; adjusted
    # returns keep it in the range the other days show
    nvda = result["symbols"].index("NVDA")
    spy = result["symbols"].index("SPY")
    assert float(result["matrix"][nvda][spy]) > -0.5


async def test_six_symbols_eleven_years_forty_windows_within_the_budget(
    client: httpx.AsyncClient, basket: None, corpus: dict[str, Records]
) -> None:
    sessions = len(corpus["AAPL"])
    rolling = {
        "length": 60,
        "step": (sessions - 60) // 39,
        "start": "2010-01-01",
        "end": "2030-01-01",
    }
    started = time.perf_counter()
    body = await correlations(client, {"symbols": list(SYMBOLS), "rolling": rolling})
    elapsed = time.perf_counter() - started
    assert 40 <= len(body["windows"]) <= 45
    assert elapsed < SECONDS, f"{len(body['windows'])} windows took {elapsed:.2f}s"
