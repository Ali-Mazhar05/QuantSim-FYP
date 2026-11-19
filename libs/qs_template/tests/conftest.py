import os
import uuid
from collections.abc import AsyncIterator

import pytest
from pydantic import SecretStr
from sqlalchemy import text

from qs_template import Database, ServiceSettings


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Skip database tests when no database is available (CI always provides one)."""
    if os.environ.get("TEST_DATABASE_URL"):
        return
    skip = pytest.mark.skip(reason="TEST_DATABASE_URL is not set")
    for item in items:
        if "db" in item.keywords:
            item.add_marker(skip)


@pytest.fixture
async def database() -> AsyncIterator[Database]:
    """A Database on a schema of its own, dropped after the test."""
    schema = f"test_{uuid.uuid4().hex[:12]}"
    base_url = os.environ["TEST_DATABASE_URL"]
    admin = Database(ServiceSettings(service_name="tests", database_url=SecretStr(base_url)))
    async with admin.transaction() as session:
        await session.execute(text(f"CREATE SCHEMA {schema}"))
    await admin.close()

    db = Database(
        ServiceSettings(
            service_name="tests", database_url=SecretStr(base_url), db_search_path=schema
        )
    )
    try:
        yield db
    finally:
        await db.close()
        cleanup = Database(ServiceSettings(service_name="tests", database_url=SecretStr(base_url)))
        async with cleanup.transaction() as session:
            await session.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        await cleanup.close()
