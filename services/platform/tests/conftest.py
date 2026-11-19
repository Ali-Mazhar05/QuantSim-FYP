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
from sqlalchemy import select, text

from qs_platform.limits import RateLimiter
from qs_platform.main import build_app
from qs_platform.models import mail_outbox, metadata
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


class PlatformClient(httpx.AsyncClient):
    """Test client that also knows the test database, to read the emails it queued."""

    database: Database


@pytest.fixture
async def client(database: Database, redis: FakeAsyncRedis) -> AsyncIterator[httpx.AsyncClient]:
    app = build_app(
        make_settings(),
        database=database,
        revocations=RevocationList(redis),
        limiter=RateLimiter(redis),
    )
    transport = httpx.ASGITransport(app=app)
    async with PlatformClient(transport=transport, base_url="http://platform") as http:
        http.database = database
        yield http


async def mails_to(database: Database, address: str) -> list[tuple[str, dict[str, Any]]]:
    """Emails queued for ``address``, oldest first, as (template, params)."""
    async with database.transaction() as session:
        rows = await session.execute(
            select(mail_outbox.c.template, mail_outbox.c.params)
            .where(mail_outbox.c.to_address == address)
            .order_by(mail_outbox.c.id)
        )
        return [(r[0], r[1]) for r in rows]


def link_token(link: str) -> str:
    """The token in an emailed link's fragment (#token=...&purpose=...)."""
    fragment = link.split("#", 1)[1]
    values = dict(part.split("=", 1) for part in fragment.split("&"))
    return values["token"]


async def last_link(client: httpx.AsyncClient, address: str, template: str) -> str:
    database = client.database  # type: ignore[attr-defined]
    links = [p["link"] for t, p in await mails_to(database, address) if t == template]
    assert links, f"no {template} email to {address}"
    link: str = links[-1]
    return link


async def invite_and_accept(
    client: httpx.AsyncClient,
    admin: str,
    username: str,
    role: str = "quant",
    password: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """Admin invites a user, who then sets their password through the emailed link."""
    body = {
        "username": username,
        "email": f"{username}@quantsim.dev",
        "display_name": username.title(),
        "role": role,
        **extra,
    }
    response = await client.post("/api/platform/users", json=body, headers=bearer(admin))
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()
    link = await last_link(client, created["email"], "invite")
    accepted = await client.post(
        "/api/platform/auth/reset-password",
        json={"token": link_token(link), "password": password or f"{username}-password-123"},
    )
    assert accepted.status_code == 200, accepted.text
    return created


async def login(client: httpx.AsyncClient, username: str, password: str) -> str:
    response = await client.post(
        "/api/platform/auth/login", json={"username": username, "password": password}
    )
    assert response.status_code == 200, response.text
    token: str = response.json()["access_token"]
    return token


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
