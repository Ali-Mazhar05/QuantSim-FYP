import asyncio
import os
import socket
import uuid
from collections.abc import Coroutine, Iterator
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

SERVICE_ROOT = Path(__file__).resolve().parents[1]


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    if os.environ.get("TEST_DATABASE_URL"):
        return
    skip = pytest.mark.skip(reason="TEST_DATABASE_URL is not set")
    for item in items:
        if "db" in item.keywords:
            item.add_marker(skip)


def run[T](coroutine: Coroutine[Any, Any, T]) -> T:
    """Run async database code from a synchronous test (Alembic runs its own loop)."""
    return asyncio.run(coroutine)


async def _execute_autocommit(url: str, statement: str) -> None:
    engine = create_async_engine(url, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as connection:
            await connection.execute(text(statement))
    finally:
        await engine.dispose()


@pytest.fixture(scope="session")
def migrated_database_url() -> Iterator[str]:
    """A brand-new database built by running every migration, dropped afterwards.

    The TimescaleDB extension is created here, as the superuser, the way db-init does in
    deployed environments: the migration itself runs without that privilege.
    """
    base_url = os.environ["TEST_DATABASE_URL"]
    name = f"market_test_{uuid.uuid4().hex[:12]}"
    run(_execute_autocommit(base_url, f'CREATE DATABASE "{name}"'))
    url = make_url(base_url).set(database=name).render_as_string(hide_password=False)
    run(_execute_autocommit(url, "CREATE EXTENSION IF NOT EXISTS timescaledb"))

    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    try:
        config = Config(str(SERVICE_ROOT / "alembic.ini"))
        config.set_main_option("script_location", str(SERVICE_ROOT / "migrations"))
        command.upgrade(config, "head")
        yield url
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
        run(_execute_autocommit(base_url, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


REAL_VENDOR_HOST = "api.tiingo.com"


class RealVendorCalled(AssertionError):
    """A test tried to reach the real vendor, whose key is shared and metered."""


@pytest.fixture(autouse=True)
def _never_reach_the_real_vendor(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail any test that resolves or connects to the real Tiingo host. Vendor tests use
    recorded fixtures or a mock transport."""
    real_getaddrinfo = socket.getaddrinfo
    real_create_connection = socket.create_connection

    def guarded_getaddrinfo(host: Any, *args: Any, **kwargs: Any) -> Any:
        if REAL_VENDOR_HOST in str(host):
            raise RealVendorCalled(f"a test resolved {REAL_VENDOR_HOST}")
        return real_getaddrinfo(host, *args, **kwargs)

    def guarded_create_connection(address: Any, *args: Any, **kwargs: Any) -> Any:
        if REAL_VENDOR_HOST in str(address[0]):
            raise RealVendorCalled(f"a test connected to {REAL_VENDOR_HOST}")
        return real_create_connection(address, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", guarded_getaddrinfo)
    monkeypatch.setattr(socket, "create_connection", guarded_create_connection)
