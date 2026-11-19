"""The read API on eleven years of real bars: what comes out of the pages is exactly what
the vendor sent, and the real splits are listed."""

from datetime import date
from decimal import Decimal
from typing import Any

import httpx
import pytest

from qs_template import Database
from tests import read_support as support
from tests.read_support import add_instrument, get_json, ingest, pages

from .conftest import Records

client = support.client
database = support.database
pytestmark = [pytest.mark.realdata, pytest.mark.db]


class RecordedSource:
    name = "recorded"

    def __init__(self, corpus: dict[str, Records]) -> None:
        self._corpus = corpus

    async def fetch_daily(self, symbol: str, start: date, end: date) -> list[dict[str, Any]]:
        low, high = start.isoformat(), end.isoformat()
        return [dict(r) for r in self._corpus[symbol] if low <= r["date"] <= high]


async def test_paged_bars_equal_the_vendor_closes_for_all_years_and_splits_are_listed(
    client: httpx.AsyncClient, database: Database, corpus: dict[str, Records]
) -> None:
    ids = {}
    for symbol in ("AAPL", "NVDA"):
        ids[symbol] = await add_instrument(database, symbol)
        dates = [date.fromisoformat(r["date"]) for r in corpus[symbol]]
        await ingest(database, RecordedSource(corpus), [ids[symbol]], (min(dates), max(dates)))

    bars = [
        item
        async for page in pages(client, f"/instruments/{ids['AAPL']}/bars", limit=700)
        for item in page["items"]
    ]
    vendor = {r["date"]: r for r in corpus["AAPL"]}
    assert [b["session_date"] for b in bars] == sorted(vendor)
    assert len(bars) > 2700  # eleven years of sessions
    for b in bars:
        source = vendor[b["session_date"]]
        assert Decimal(b["close"]) == source["close"], b["session_date"]
        assert Decimal(b["volume"]) == source["volume"], b["session_date"]

    nvda = await get_json(client, f"/instruments/{ids['NVDA']}/corporate-actions")
    splits = {
        a["session_date"]: Decimal(a["split_factor"]) for a in nvda if a["kind"] != "dividend"
    }
    assert {"2021-07-20", "2024-06-10"} <= set(splits)
    assert splits["2021-07-20"] == 4 and splits["2024-06-10"] == 10
