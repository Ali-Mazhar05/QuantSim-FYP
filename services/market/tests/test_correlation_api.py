"""POST /correlations through the real app against a database loaded by the real pipeline
runner with the recorded AAPL and PEER responses."""

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

import httpx
import numpy as np
import pandas as pd
import pytest
from sqlalchemy import update

from qs_market.models import bar
from qs_market.vendor.fixture import FixtureSource
from qs_template import Database
from qs_template.auth import Role
from tests import read_support as support
from tests.instrument_support import API, bearer, make_token
from tests.read_support import get_json, pages

client = support.client
database = support.database
pytestmark = pytest.mark.db

OVERLAP = {"start": "2024-01-02", "end": "2024-02-13"}
SCALED = ("open", "high", "low", "close", "adj_open", "adj_high", "adj_low", "adj_close")


async def ask(
    http: httpx.AsyncClient, body: dict[str, Any], role: Role = Role.VIEWER
) -> httpx.Response:
    return await http.post(f"{API}/correlations", json=body, headers=bearer(make_token(role)))


class PeerSource:
    """The recorded AAPL bars under the symbol PEER with every price scaled by a small
    session-dependent factor, so PEER is correlated with AAPL but not identical and the
    two share every session."""

    name = "fixture"

    def __init__(self) -> None:
        self._base = FixtureSource(support.FIXTURES)

    async def fetch_daily(self, symbol: str, start: date, end: date) -> list[dict[str, Any]]:
        rows = await self._base.fetch_daily("AAPL", start, end)
        if symbol != "PEER":
            return rows
        for i, row in enumerate(rows):
            factor = Decimal(100 + ((i * 7) % 5) - 2) / Decimal(100)
            for key in SCALED:
                if row.get(key) is not None:
                    row[key] = (row[key] * factor).quantize(Decimal("0.00000001"))
        return rows


async def both_loaded(database: Database) -> dict[str, uuid.UUID]:
    """AAPL and PEER over the same sessions."""
    ids: dict[str, uuid.UUID] = {}
    for symbol in ("AAPL", "PEER"):
        ids[symbol] = await support.add_instrument(database, symbol)
        await support.ingest(
            database, PeerSource(), [ids[symbol]], (date(2024, 1, 2), date(2024, 2, 13))
        )
    return ids


async def test_matrix_equals_pandas_on_the_stored_returns(
    client: httpx.AsyncClient, database: Database
) -> None:
    ids = await both_loaded(database)
    response = await ask(
        client, {"symbols": ["PEER", "AAPL"], "windows": [OVERLAP], "min_observations": 5}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    [window] = body["windows"]
    assert window["symbols"] == ["AAPL", "PEER"]
    frame = pd.DataFrame()
    for symbol in ("AAPL", "PEER"):
        rows = [
            r
            async for p in pages(client, f"/instruments/{ids[symbol]}/returns", limit=100)
            for r in p["items"]
            if r["adj_log_return"] is not None
        ]
        frame[symbol] = pd.Series(
            {r["session_date"]: float(r["adj_log_return"]) for r in rows}, dtype=float
        )
    frame = frame.dropna()
    frame = frame[(frame.index >= OVERLAP["start"]) & (frame.index <= OVERLAP["end"])]
    assert window["n_obs"] == len(frame) > 5
    expected = frame.corr().to_numpy()
    got = np.array([[float(v) for v in row] for row in window["matrix"]])
    assert np.allclose(got, expected, atol=1e-8)
    assert window["matrix"][0][0] == "1.00000000"
    assert window["matrix"][0][1] == window["matrix"][1][0]
    assert body["method"] and body["min_observations"] == 5


async def test_ids_and_symbols_give_the_same_fingerprint_in_any_order(
    client: httpx.AsyncClient, database: Database
) -> None:
    ids = await both_loaded(database)
    request = {"windows": [OVERLAP], "min_observations": 5}
    a = (await ask(client, {**request, "symbols": ["AAPL", "PEER"]})).json()
    b = (await ask(client, {**request, "symbols": ["PEER", "AAPL"]})).json()
    c = (
        await ask(client, {**request, "instrument_ids": [str(ids["PEER"]), str(ids["AAPL"])]})
    ).json()
    assert a == b == c
    assert len(a["windows"][0]["fingerprint"]) == 64


async def test_a_vendor_correction_changes_the_fingerprint_and_nothing_else_does(
    client: httpx.AsyncClient, database: Database
) -> None:
    ids = await both_loaded(database)
    body = {"symbols": ["AAPL", "PEER"], "windows": [OVERLAP], "min_observations": 5}
    first = (await ask(client, body)).json()["windows"][0]
    again = (await ask(client, body)).json()["windows"][0]
    assert first == again
    async with database.transaction() as session:
        await session.execute(
            update(bar)
            .where(bar.c.instrument_id == ids["AAPL"], bar.c.session_date == date(2024, 1, 10))
            .values(content_hash="corrected-by-the-vendor", revision=2)
        )
    changed = (await ask(client, body)).json()["windows"][0]
    assert changed["fingerprint"] != first["fingerprint"]
    assert changed["matrix"] == first["matrix"]


async def test_rolling_windows_and_the_minimum(
    client: httpx.AsyncClient, database: Database
) -> None:
    await both_loaded(database)
    rolling = {"length": 10, "step": 5, **OVERLAP}
    body = (
        await ask(client, {"symbols": ["AAPL", "PEER"], "rolling": rolling, "min_observations": 5})
    ).json()
    windows = body["windows"]
    sessions = windows[0]["n_obs"]
    assert sessions == 10
    assert len(windows) >= 2
    assert all(w["n_obs"] == 10 for w in windows)
    assert len({w["fingerprint"] for w in windows}) == len(windows)
    assert windows[1]["start"] > windows[0]["start"]
    short = (await ask(client, {"symbols": ["AAPL", "PEER"], "windows": [OVERLAP]})).json()[
        "windows"
    ][0]
    assert short["n_obs"] >= 5
    below = (
        await ask(
            client,
            {"symbols": ["AAPL", "PEER"], "windows": [OVERLAP], "min_observations": 500},
        )
    ).json()["windows"][0]
    assert below["matrix"] == [[None, None], [None, None]]
    assert {u["reason"] for u in below["unavailable"]} == {"insufficient_observations"}


async def test_problem_details(client: httpx.AsyncClient, database: Database) -> None:
    ids = await both_loaded(database)
    empty = await support.add_instrument(database, "EMPTY")
    window = {"windows": [OVERLAP]}

    unknown = await ask(client, {"symbols": ["AAPL", "ZZZZ"], **window})
    assert unknown.status_code == 404
    assert unknown.json()["unknown"] == ["ZZZZ"]
    missing = await ask(client, {"instrument_ids": [str(ids["AAPL"]), str(uuid.uuid4())], **window})
    assert missing.status_code == 404

    for body in (
        {"symbols": [], **window},
        {"symbols": ["AAPL"], **window},
        {"symbols": ["AAPL", "AAPL"], **window},
        {**window},
        {"symbols": ["AAPL", "PEER"], "instrument_ids": [str(ids["AAPL"])], **window},
        {"symbols": ["AAPL", "PEER"]},
        {"symbols": ["AAPL", "PEER"], **window, "rolling": {"length": 5, "step": 1, **OVERLAP}},
        {"symbols": ["AAPL", "PEER"], "windows": []},
        {"symbols": ["AAPL", "PEER"], "windows": [{"start": "2024-06-21", "end": "2024-05-28"}]},
        {"symbols": ["AAPL", "PEER"], "rolling": {"length": 1, "step": 1, **OVERLAP}},
        {"symbols": ["AAPL", "PEER"], "windows": [OVERLAP], "min_observations": 1},
    ):
        response = await ask(client, body)
        assert response.status_code == 422, (body, response.text)
        assert response.headers["content-type"].startswith("application/problem+json")

    none = await ask(client, {"symbols": ["AAPL", "EMPTY"], **window})
    assert none.status_code == 422
    assert none.json()["instruments"] == ["EMPTY"]
    assert empty

    cap = await ask(
        client, {"symbols": ["AAPL", "PEER"], "windows": [OVERLAP] * 251, "min_observations": 5}
    )
    assert cap.status_code == 422
    huge = await ask(
        client,
        {
            "symbols": ["AAPL", "PEER"],
            "rolling": {"length": 2, "step": 1, "start": "2024-01-01", "end": "2024-06-21"},
        },
    )
    assert huge.status_code == 200
    assert len(huge.json()["windows"]) > 20


async def test_roles_and_authentication(client: httpx.AsyncClient, database: Database) -> None:
    await both_loaded(database)
    body = {"symbols": ["AAPL", "PEER"], "windows": [OVERLAP], "min_observations": 5}
    for role in Role:
        response = await ask(client, body, role)
        assert response.status_code == 200, (role, response.text)
    anonymous = await client.post(f"{API}/correlations", json=body)
    assert anonymous.status_code == 401
    forged = await client.post(
        f"{API}/correlations", json=body, headers=bearer(make_token(Role.ADMIN, forged=True))
    )
    assert forged.status_code == 401
    assert await get_json(client, "/data-quality", Role.ADMIN) is not None


async def test_instruments_with_no_shared_session_give_an_empty_window(
    client: httpx.AsyncClient, database: Database
) -> None:
    for symbol, window in support.WINDOWS.items():
        new_id = await support.add_instrument(database, symbol)
        await support.ingest(database, FixtureSource(support.FIXTURES), [new_id], window)
    body = await ask(
        client,
        {
            "symbols": ["AAPL", "NVDA"],
            "windows": [{"start": "2024-01-01", "end": "2024-06-30"}],
        },
    )
    assert body.status_code == 200
    [window] = body.json()["windows"]
    assert window["n_obs"] == 0
    assert window["matrix"] == [[None, None], [None, None]]
