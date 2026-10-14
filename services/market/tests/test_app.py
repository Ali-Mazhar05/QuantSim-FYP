"""Operations endpoints of the market service (PRD FR-31): the health check reports the
deployed Content hash, and readiness fails while the database or Redis is unreachable."""

from collections.abc import AsyncIterator

import httpx
import pytest
from fakeredis import FakeAsyncRedis
from pydantic import SecretStr, ValidationError

from qs_market.main import build_app
from qs_market.settings import MarketSettings
from qs_template import Database
from qs_template.revocation import RevocationList

UNREACHABLE_DB = "postgresql+asyncpg://market:market@127.0.0.1:1/market"


def make_settings() -> MarketSettings:
    return MarketSettings(
        database_url=SecretStr(UNREACHABLE_DB),
        redis_url=SecretStr("redis://unused"),
        content_hash="0123456789ab",
    )


class BrokenRedis(FakeAsyncRedis):
    async def ping(self, **kwargs: object) -> bool:
        raise ConnectionError("redis is down")


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    settings = make_settings()
    database = Database(settings)
    app = build_app(settings, database=database, revocations=RevocationList(BrokenRedis()))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://market") as http:
        yield http
    await database.close()


async def test_health_reports_the_service_and_its_content_hash(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/market/health")
    assert response.status_code == 200
    assert response.json()["service"] == "market"
    assert response.json()["content_hash"] == "0123456789ab"


async def test_ready_is_503_while_the_database_and_redis_are_unreachable(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get("/api/market/ready")
    assert response.status_code == 503
    assert response.json()["checks"] == {"database": "unavailable", "redis": "unavailable"}


def test_settings_fail_fast_without_redis() -> None:
    with pytest.raises(ValidationError, match="redis_url"):
        MarketSettings(database_url=SecretStr(UNREACHABLE_DB))
