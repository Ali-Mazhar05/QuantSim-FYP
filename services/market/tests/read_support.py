"""Loads recorded bars through the real pipeline runner so the read API tests check what
the API returns against what was ingested."""

import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import insert, select

from qs_market.models import instrument
from qs_market.pipeline.runner import PipelineConfig, RunOutcome, run_next
from qs_market.pipeline.runs import create_run
from qs_market.vendor.fixture import FixtureSource
from qs_template import Database
from qs_template.auth import Role
from tests import instrument_support as support
from tests.instrument_support import API, bearer, make_token

FIXTURES = Path(__file__).parent / "fixtures"
AS_OF = datetime(2025, 1, 6, 12, 0, tzinfo=UTC)
WINDOWS = {
    "AAPL": (date(2024, 1, 2), date(2024, 2, 13)),
    "NVDA": (date(2024, 5, 28), date(2024, 6, 21)),
}

client = support.client
database = support.database


async def add_instrument(db: Database, symbol: str, *, status: str = "active") -> uuid.UUID:
    async with db.transaction() as session:
        return (
            await session.execute(
                insert(instrument)
                .values(
                    symbol=symbol,
                    name=symbol,
                    sector="Technology",
                    exchange="XNAS",
                    calendar="XNYS",
                    currency="USD",
                    asset_class="equity",
                    vendor_symbol=symbol,
                    status=status,
                )
                .returning(instrument.c.id)
            )
        ).scalar_one()


async def ingest(
    db: Database, source: Any, ids: list[uuid.UUID], window: tuple[date, date]
) -> RunOutcome:
    async with db.transaction() as session:
        await create_run(
            session,
            mode="backfill",
            window=window,
            instrument_ids=ids,
            idempotency_key=None,
            requested_by="tests",
            vendor="fixture",
        )
    outcome = await run_next(
        db, lambda run: source, PipelineConfig(backfill_start=window[0]), as_of=AS_OF
    )
    assert outcome is not None
    assert outcome.status == "succeeded", outcome.error
    return outcome


@pytest.fixture
async def loaded(database: Database) -> dict[str, uuid.UUID]:
    """AAPL and NVDA, ingested from the recorded responses. Returns symbol -> id."""
    ids: dict[str, uuid.UUID] = {}
    for symbol, window in WINDOWS.items():
        ids[symbol] = await add_instrument(database, symbol)
        await ingest(database, FixtureSource(FIXTURES), [ids[symbol]], window)
    return ids


def recorded(symbol: str) -> list[dict[str, Any]]:
    return json.loads((FIXTURES / f"{symbol}.json").read_text(encoding="utf-8"))  # type: ignore[no-any-return]


async def get_json(
    http: httpx.AsyncClient, path: str, role: Role = Role.VIEWER, **params: Any
) -> Any:
    response = await http.get(f"{API}{path}", params=params, headers=bearer(make_token(role)))
    assert response.status_code == 200, response.text
    return response.json()


async def instrument_id(db: Database, symbol: str) -> uuid.UUID:
    async with db.transaction() as session:
        return (
            await session.execute(select(instrument.c.id).where(instrument.c.symbol == symbol))
        ).scalar_one()


async def pages(
    http: httpx.AsyncClient, path: str, role: Role = Role.VIEWER, **params: Any
) -> AsyncIterator[dict[str, Any]]:
    """Follow next_cursor to the end, yielding one response per page."""
    cursor = None
    while True:
        extra = {"cursor": cursor} if cursor else {}
        page = await get_json(http, path, role, **params, **extra)
        yield page
        cursor = page["next_cursor"]
        if cursor is None:
            return
