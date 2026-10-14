"""Shared pieces of the instrument master tests: a database on the migrated schema,
signed tokens for every role and an app wired with the matching public key."""

import json
import time
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fakeredis import FakeAsyncRedis
from jwt.algorithms import RSAAlgorithm
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from qs_market.main import build_app
from qs_market.settings import MarketSettings
from qs_template import Database
from qs_template.auth import Authenticator, Role, StaticKeys
from qs_template.revocation import RevocationList

API = "/api/market"
KEY_ID = "test-key-1"
_PRIVATE = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_FORGED = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _jwks() -> dict[str, Any]:
    public: dict[str, Any] = json.loads(RSAAlgorithm.to_jwk(_PRIVATE.public_key()))
    public.update({"kid": KEY_ID, "alg": "RS256", "use": "sig"})
    return {"keys": [public]}


def make_token(role: Role, *, forged: bool = False, user_id: uuid.UUID | None = None) -> str:
    now = int(time.time())
    claims = {
        "sub": str(user_id or uuid.uuid4()),
        "username": f"{role.value}.user",
        "role": role.value,
        "jti": uuid.uuid4().hex,
        "iat": now,
        "exp": now + 600,
        "iss": "quantsim-platform",
        "aud": "quantsim",
    }
    key = _FORGED if forged else _PRIVATE
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": KEY_ID})


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def make_settings(url: str, **extra: Any) -> MarketSettings:
    return MarketSettings(
        database_url=SecretStr(url),
        redis_url=SecretStr("redis://unused"),
        auth_jwks_url="http://platform/jwks",
        **extra,
    )


ALL_TABLES = (
    "outbox, return_series, corporate_action, data_gap, rejected_bar, staging_bar, bar_revision, "
    "bar, ingestion_run_item, ingestion_run, instrument"
)


@pytest.fixture
async def database(migrated_database_url: str) -> AsyncIterator[Database]:
    db = Database(make_settings(migrated_database_url))
    async with db.transaction() as session:
        # bar is a hypertable and keeps its rows when instrument is truncated, so every
        # table is listed: a test must never see another test's data
        await session.execute(text(f"TRUNCATE {ALL_TABLES} CASCADE"))
    try:
        yield db
    finally:
        await db.close()


@pytest.fixture
async def session(database: Database) -> AsyncIterator[AsyncSession]:
    async with database.transaction() as session:
        yield session


@pytest.fixture
async def client(
    database: Database, migrated_database_url: str
) -> AsyncIterator[httpx.AsyncClient]:
    settings = make_settings(migrated_database_url)
    auth = Authenticator(settings, jwks=StaticKeys(_jwks()))
    app = build_app(
        settings,
        database=database,
        revocations=RevocationList(FakeAsyncRedis()),
        authenticator=auth,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://market"
    ) as http:
        yield http


NEW_INSTRUMENT: dict[str, Any] = {
    "symbol": "ZZTEST",
    "name": "Test Corp",
    "sector": "Technology",
    "exchange": "XNAS",
    "currency": "USD",
    "asset_class": "equity",
}


async def insert_bar(
    session: AsyncSession, instrument_id: Any, session_date: date, close: str
) -> None:
    price = Decimal(close)
    close_time = datetime(session_date.year, session_date.month, session_date.day, 21, tzinfo=UTC)
    await session.execute(
        text(
            "INSERT INTO bar (instrument_id, session_date, ts, open, high, low, close, volume,"
            " content_hash, run_id, vendor, ruleset_version) VALUES (:i, :d, :ts, :p, :p, :p, :p,"
            " 100, 'h', :run, 'fixture', 'v1')"
        ),
        {"i": instrument_id, "d": session_date, "ts": close_time, "p": price, "run": uuid.uuid4()},
    )
