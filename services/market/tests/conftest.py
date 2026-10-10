import asyncio
import os
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

    The CI database user is a superuser, so the first migration can create the
    TimescaleDB extension itself, as db-init does in deployed environments.
    """
    base_url = os.environ["TEST_DATABASE_URL"]
    name = f"market_test_{uuid.uuid4().hex[:12]}"
    run(_execute_autocommit(base_url, f'CREATE DATABASE "{name}"'))
    url = make_url(base_url).set(database=name).render_as_string(hide_password=False)

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
