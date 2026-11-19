"""Display intervals and metrics through the API, against a real database loaded through
the real pipeline (FYP TC-MKT-01, TC-MKT-02, TC-MET-01, NFR-PERF-01, FR-MKT-03).

The oracle is an independent implementation: pandas resampling for the candles and numpy
for the metrics, both fed from the recorded vendor responses, not from the database."""

import math
import time
import uuid
from datetime import date
from decimal import Decimal

import httpx
import numpy as np
import pandas as pd
import pytest
from sqlalchemy import text

from qs_template import Database
from qs_template.auth import Role
from tests import read_support as support
from tests.instrument_support import API, bearer, make_token
from tests.read_support import WINDOWS, add_instrument, get_json, recorded

client = support.client
database = support.database
loaded = support.loaded
pytestmark = pytest.mark.db

# pandas bucket for each interval: ISO week (Monday to Sunday), calendar month, calendar year
FREQUENCY = {"weekly": "W-SUN", "monthly": "ME", "yearly": "YE"}


def ingested(symbol: str) -> pd.DataFrame:
    low, high = (d.isoformat() for d in WINDOWS[symbol])
    rows = [r for r in recorded(symbol) if low <= r["date"][:10] <= high]
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime([r["date"][:10] for r in rows]),
            "open": [r["open"] for r in rows],
            "high": [r["high"] for r in rows],
            "low": [r["low"] for r in rows],
            "close": [r["close"] for r in rows],
            "adj_close": [r["adjClose"] for r in rows],
            "volume": [r["volume"] for r in rows],
        }
    )
    return frame.sort_values("date").reset_index(drop=True)


def expected_candles(symbol: str, interval: str) -> list[dict[str, object]]:
    frame = ingested(symbol).set_index("date")
    grouped = frame.resample(FREQUENCY[interval])
    out = []
    for _, group in grouped:
        if group.empty:
            continue  # a period with no session is not a candle
        out.append(
            {
                "period_start": group.index[0].date().isoformat(),
                "session_date": group.index[-1].date().isoformat(),
                "open": group["open"].iloc[0],
                "high": group["high"].max(),
                "low": group["low"].min(),
                "close": group["close"].iloc[-1],
                "volume": group["volume"].sum(),
                "sessions": len(group),
            }
        )
    return out


async def test_weekly_monthly_and_yearly_candles_match_pandas(
    client: httpx.AsyncClient, loaded: dict[str, uuid.UUID]
) -> None:
    for symbol, instrument_id in loaded.items():
        for interval in ("weekly", "monthly", "yearly"):
            body = await get_json(
                client, f"/instruments/{instrument_id}/candles", interval=interval
            )
            assert body["interval"] == interval
            wanted = expected_candles(symbol, interval)
            assert len(body["items"]) == len(wanted), (symbol, interval)
            for got, want in zip(body["items"], wanted, strict=True):
                assert got["period_start"] == want["period_start"], (symbol, interval)
                assert got["session_date"] == want["session_date"], (symbol, interval)
                assert got["sessions"] == want["sessions"], (symbol, interval)
                for field in ("open", "high", "low", "close"):
                    assert Decimal(got[field]) == Decimal(str(want[field])), (
                        symbol,
                        interval,
                        field,
                    )
                assert Decimal(got["volume"]) == Decimal(int(want["volume"])), (symbol, interval)  # type: ignore[call-overload]


async def test_daily_candles_are_the_stored_bars(
    client: httpx.AsyncClient, loaded: dict[str, uuid.UUID]
) -> None:
    body = await get_json(client, f"/instruments/{loaded['AAPL']}/candles")
    bars = await get_json(client, f"/instruments/{loaded['AAPL']}/bars")
    assert body["interval"] == "daily"
    assert [c["session_date"] for c in body["items"]] == [b["session_date"] for b in bars["items"]]
    assert [c["close"] for c in body["items"]] == [b["close"] for b in bars["items"]]
    assert all(c["sessions"] == 1 for c in body["items"])


async def test_date_range_bounds_the_candles_inclusively(
    client: httpx.AsyncClient, loaded: dict[str, uuid.UUID]
) -> None:
    frame = ingested("AAPL")
    low, high = frame["date"].iloc[3], frame["date"].iloc[9]
    body = await get_json(
        client,
        f"/instruments/{loaded['AAPL']}/candles",
        interval="weekly",
        **{"from": low.date().isoformat(), "to": high.date().isoformat()},
    )
    inside = frame[(frame["date"] >= low) & (frame["date"] <= high)]
    # the first and last week hold only the sessions inside the window
    assert sum(c["sessions"] for c in body["items"]) == len(inside)
    assert body["items"][0]["period_start"] == low.date().isoformat()
    assert body["items"][-1]["session_date"] == high.date().isoformat()


async def test_a_range_with_no_observations_is_an_empty_success(
    client: httpx.AsyncClient, loaded: dict[str, uuid.UUID]
) -> None:
    target = loaded["AAPL"]
    for interval in ("daily", "weekly", "monthly", "yearly"):
        params = {"interval": interval, "from": "2030-01-01"}
        body = await get_json(client, f"/instruments/{target}/candles", Role.VIEWER, **params)
        assert body["items"] == []
        metrics = await get_json(client, f"/instruments/{target}/metrics", Role.VIEWER, **params)
        assert metrics["observations"] == 0
        assert metrics["period_return"] is None
        assert metrics["annualised_volatility"] is None
        assert metrics["max_drawdown"] is None
        assert set(metrics["unavailable"]) == {
            "period_return",
            "annualised_volatility",
            "max_drawdown",
        }


async def test_invalid_input_is_refused_not_guessed(
    client: httpx.AsyncClient, loaded: dict[str, uuid.UUID]
) -> None:
    target = loaded["AAPL"]
    headers = bearer(make_token(Role.VIEWER))
    for path in ("candles", "metrics"):
        url = f"{API}/instruments/{target}/{path}"
        assert (
            await client.get(url, params={"interval": "hourly"}, headers=headers)
        ).status_code == 422
        reversed_range = {"from": "2024-02-01", "to": "2024-01-01"}
        assert (await client.get(url, params=reversed_range, headers=headers)).status_code == 422
        assert (
            await client.get(url, params={"from": "yesterday"}, headers=headers)
        ).status_code == 422
        assert (await client.get(url)).status_code == 401
        missing = f"{API}/instruments/{uuid.uuid4()}/{path}"
        assert (await client.get(missing, headers=headers)).status_code == 404


@pytest.mark.parametrize("interval", ["daily", "weekly", "monthly"])
async def test_metrics_match_numpy_on_the_split_adjusted_series(
    client: httpx.AsyncClient, loaded: dict[str, uuid.UUID], interval: str
) -> None:
    # NVDA split 10 for 1 on 2024-06-10: the raw close drops by 90%, the adjusted does not
    body = await get_json(client, f"/instruments/{loaded['NVDA']}/metrics", interval=interval)
    assert body["price_basis"] == "adjusted_close"

    frame = ingested("NVDA").set_index("date")
    if interval == "daily":
        prices = frame["adj_close"].to_numpy()
    else:
        prices = frame["adj_close"].resample(FREQUENCY[interval]).last().dropna().to_numpy()
    assert body["observations"] == len(prices)

    periods = {"daily": 252, "weekly": 52, "monthly": 12}[interval]
    peaks = np.maximum.accumulate(prices)
    expected_drawdown = float(np.min((prices - peaks) / peaks))
    assert abs(float(body["period_return"]) - float(prices[-1] / prices[0] - 1)) < 1e-8
    assert abs(float(body["max_drawdown"]) - expected_drawdown) < 1e-8

    log_returns = np.diff(np.log(prices))
    if len(log_returns) < 2:
        # two monthly points have one return, and one return has no sample deviation
        assert body["annualised_volatility"] is None
        assert set(body["unavailable"]) == {"annualised_volatility"}
    else:
        expected_vol = float(np.std(log_returns, ddof=1) * math.sqrt(periods))
        assert abs(float(body["annualised_volatility"]) - expected_vol) < 1e-8
        assert body["unavailable"] == {}


async def test_the_raw_split_would_have_looked_like_a_crash(
    client: httpx.AsyncClient, loaded: dict[str, uuid.UUID]
) -> None:
    frame = ingested("NVDA")
    raw_return = float(frame["close"].iloc[-1] / frame["close"].iloc[0] - 1)
    assert raw_return < -0.8  # the trap the adjusted basis avoids
    body = await get_json(client, f"/instruments/{loaded['NVDA']}/metrics")
    assert float(body["period_return"]) > -0.5


async def test_metrics_with_two_observations_report_why_volatility_is_missing(
    client: httpx.AsyncClient, loaded: dict[str, uuid.UUID]
) -> None:
    frame = ingested("AAPL")
    two = {
        "from": frame["date"].iloc[0].date().isoformat(),
        "to": frame["date"].iloc[1].date().isoformat(),
    }
    body = await get_json(client, f"/instruments/{loaded['AAPL']}/metrics", **two)
    assert body["observations"] == 2
    assert body["period_return"] is not None and body["max_drawdown"] is not None
    assert body["annualised_volatility"] is None
    assert set(body["unavailable"]) == {"annualised_volatility"}


async def test_every_number_is_a_string_never_a_float(
    client: httpx.AsyncClient, loaded: dict[str, uuid.UUID]
) -> None:
    target = loaded["AAPL"]
    body = await get_json(client, f"/instruments/{target}/candles", interval="weekly")
    for item in body["items"]:
        for key in ("open", "high", "low", "close", "volume"):
            assert isinstance(item[key], str) and "e" not in item[key].lower()
    metrics = await get_json(client, f"/instruments/{target}/metrics")
    for key in ("period_return", "annualised_volatility", "max_drawdown"):
        assert isinstance(metrics[key], str)


async def test_five_years_of_one_symbol_answer_in_under_a_second(
    client: httpx.AsyncClient, database: Database
) -> None:
    """NFR-PERF-01: about 1,250 daily rows at the backend-query layer, under one second."""
    big = await add_instrument(database, "FIVE")
    async with database.transaction() as session:
        await session.execute(
            text(
                "INSERT INTO bar (instrument_id, session_date, ts, open, high, low, close,"
                " volume, adj_close, content_hash, run_id, vendor, ruleset_version)"
                " SELECT :i, d::date, d + interval '21 hours', 10, 12, 9, 11, 1000, 11, 'h',"
                " :r, 'fixture', 'v1'"
                " FROM generate_series(date '2019-01-01', date '2019-01-01' + 1249,"
                " interval '1 day') AS g(d)"
            ),
            {"i": big, "r": uuid.uuid4()},
        )
    window = {"from": "2019-01-01", "to": date(2022, 6, 4).isoformat()}
    await get_json(client, f"/instruments/{big}/quote")  # warm the connection pool
    for path, params in (
        ("bars", {**window, "limit": 2000}),
        ("candles", {**window, "interval": "daily"}),
        ("candles", {**window, "interval": "weekly"}),
        ("metrics", {**window, "interval": "daily"}),
    ):
        started = time.perf_counter()
        body = await get_json(client, f"/instruments/{big}/{path}", **params)
        elapsed = time.perf_counter() - started
        assert elapsed < 1.0, f"{path} {params.get('interval')}: {elapsed:.2f}s"
        if path == "candles" and params["interval"] == "daily":
            assert len(body["items"]) == 1250
