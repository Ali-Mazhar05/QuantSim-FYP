"""POST a run through the API, execute it, GET it, on real recorded bars. The expected
bar counts come from the corpus files, not from the pipeline."""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from typing import Any

import httpx
import pytest
from fakeredis import FakeAsyncRedis
from pydantic import SecretStr
from sqlalchemy import func, select, text

from qs_market.main import build_app
from qs_market.models import bar, instrument
from qs_market.pipeline.runner import PipelineConfig, run_next
from qs_market.seed import seed_instruments
from qs_market.settings import MarketSettings
from qs_template import Database
from qs_template.auth import Authenticator, Role, StaticKeys
from qs_template.revocation import RevocationList
from tests.instrument_support import API, _jwks, bearer, make_token

from .conftest import Records
from .test_pipeline_on_real_data import TABLES, RecordedSource

pytestmark = [pytest.mark.realdata, pytest.mark.db]

SYMBOLS = ("AAPL", "KO")


@pytest.fixture
async def api(migrated_database_url: str) -> AsyncIterator[tuple[httpx.AsyncClient, Database]]:
    settings = MarketSettings(
        database_url=SecretStr(migrated_database_url),
        redis_url=SecretStr("redis://unused"),
        auth_jwks_url="http://platform/jwks",
    )
    database = Database(settings)
    async with database.transaction() as session:
        await session.execute(text(f"TRUNCATE {TABLES} CASCADE"))
        await seed_instruments(session)
    app = build_app(
        settings,
        database=database,
        revocations=RevocationList(FakeAsyncRedis()),
        authenticator=Authenticator(settings, jwks=StaticKeys(_jwks())),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://market"
    ) as http:
        yield http, database
    async with database.transaction() as session:
        await session.execute(text(f"TRUNCATE {TABLES} CASCADE"))
    await database.close()


async def test_post_run_get_on_real_bars_matches_the_corpus(
    api: tuple[httpx.AsyncClient, Database],
    corpus: dict[str, Records],
    window: tuple[date, date],
) -> None:
    client, database = api
    headers = bearer(make_token(Role.ADMIN))
    async with database.transaction() as session:
        rows = (
            await session.execute(
                select(instrument.c.symbol, instrument.c.id).where(instrument.c.symbol.in_(SYMBOLS))
            )
        ).all()
    ids = {symbol: instrument_id for symbol, instrument_id in rows}

    posted = await client.post(
        f"{API}/ingestion-runs",
        json={
            "mode": "backfill",
            "start": window[0].isoformat(),
            "end": window[1].isoformat(),
            "instrument_ids": [str(i) for i in ids.values()],
        },
        headers=headers,
    )
    assert posted.status_code == 202
    run_id = posted.json()["id"]

    outcome = await run_next(
        database,
        lambda run: RecordedSource(corpus),
        PipelineConfig(backfill_start=window[0]),
        as_of=datetime.now(UTC),
    )
    assert outcome is not None and str(outcome.run_id) == run_id

    detail: dict[str, Any] = (
        await client.get(f"{API}/ingestion-runs/{run_id}", headers=headers)
    ).json()
    assert detail["status"] == "succeeded", detail["error"]
    items = {i["symbol"]: i for i in detail["items"]}
    assert set(items) == set(SYMBOLS)
    for symbol in SYMBOLS:
        expected = len(corpus[symbol])
        assert items[symbol]["received"] == expected
        assert items[symbol]["new_bars"] == expected
        assert items[symbol]["rejected"] == 0
    assert detail["report"]["new_bars"] == sum(len(corpus[s]) for s in SYMBOLS)

    async with database.transaction() as session:
        stored = (
            await session.execute(
                select(func.count()).select_from(bar).where(bar.c.instrument_id.in_(ids.values()))
            )
        ).scalar_one()
    assert stored == detail["report"]["new_bars"]
    rejected = await client.get(f"{API}/ingestion-runs/{run_id}/rejected", headers=headers)
    assert rejected.json()["total"] == 0
    # An id that does not exist is a 404
    missing = await client.get(f"{API}/ingestion-runs/{uuid.uuid4()}", headers=headers)
    assert missing.status_code == 404
