import base64
import os
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fakeredis import FakeAsyncRedis
from pydantic import SecretStr
from sqlalchemy import text

from qs_platform.main import build_app
from qs_platform.models import metadata
from qs_platform.service import create_first_admin
from qs_platform.settings import PlatformSettings
from qs_template import Database, ServiceSettings
from qs_template.audit import AUDIT_SETUP_STATEMENTS, audit_table_statements
from qs_template.messaging import messaging_metadata
from qs_template.revocation import RevocationList

ADMIN_PASSWORD = "admin-password-123"


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    if os.environ.get("TEST_DATABASE_URL"):
        return
    skip = pytest.mark.skip(reason="TEST_DATABASE_URL is not set")
    for item in items:
        if "db" in item.keywords:
            item.add_marker(skip)


def make_signing_key() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    return base64.b64encode(pem).decode()


SIGNING_KEY = make_signing_key()


def make_settings(**overrides: Any) -> PlatformSettings:
    values: dict[str, Any] = {
        "database_url": SecretStr(os.environ.get("TEST_DATABASE_URL", "postgresql+asyncpg://x/y")),
        "redis_url": SecretStr("redis://unused"),
        "signing_key": SecretStr(SIGNING_KEY),
        "signing_key_id": "test-key-1",
        "login_max_failures": 3,
        "login_lockout_seconds": 60,
    }
    values.update(overrides)
    return PlatformSettings(**values)


@pytest.fixture
async def database() -> AsyncIterator[Database]:
    """platform_db's tables in a schema of their own, dropped after the test."""
    schema = f"test_{uuid.uuid4().hex[:12]}"
    base_url = os.environ["TEST_DATABASE_URL"]
    admin = Database(ServiceSettings(service_name="tests", database_url=SecretStr(base_url)))
    async with admin.transaction() as session:
        await session.execute(text(f"CREATE SCHEMA {schema}"))
    await admin.close()

    db = Database(make_settings(db_search_path=schema))
    async with db.engine.begin() as connection:
        await connection.run_sync(metadata.create_all)
        await connection.run_sync(messaging_metadata.create_all)
        statements = (
            *AUDIT_SETUP_STATEMENTS,
            *audit_table_statements("users", exclude=("password_hash",)),
        )
        for statement in statements:
            await connection.exec_driver_sql(statement)
    async with db.transaction() as session:
        await create_first_admin(
            session, username="admin", email="admin@quantsim.dev", password=ADMIN_PASSWORD
        )
    try:
        yield db
    finally:
        await db.close()
        cleanup = Database(ServiceSettings(service_name="tests", database_url=SecretStr(base_url)))
        async with cleanup.transaction() as session:
            await session.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        await cleanup.close()


@pytest.fixture
def redis() -> FakeAsyncRedis:
    return FakeAsyncRedis()


@pytest.fixture
async def client(database: Database, redis: FakeAsyncRedis) -> AsyncIterator[httpx.AsyncClient]:
    app = build_app(make_settings(), database=database, revocations=RevocationList(redis))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://platform") as http:
        yield http


async def login(client: httpx.AsyncClient, username: str, password: str) -> str:
    response = await client.post(
        "/api/platform/auth/login", json={"username": username, "password": password}
    )
    assert response.status_code == 200, response.text
    token: str = response.json()["access_token"]
    return token


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
