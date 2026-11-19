import os

import pytest
from pydantic import SecretStr

from __pkg__.settings import __Class__Settings


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Skip database tests when no database is available (CI always provides one)."""
    if os.environ.get("TEST_DATABASE_URL"):
        return
    skip = pytest.mark.skip(reason="TEST_DATABASE_URL is not set")
    for item in items:
        if "db" in item.keywords:
            item.add_marker(skip)


@pytest.fixture
def settings() -> __Class__Settings:
    return __Class__Settings(
        database_url=SecretStr("postgresql+asyncpg://unused:unused@127.0.0.1:1/unused"),
        redis_url=SecretStr("redis://127.0.0.1:1/0"),
        auth_jwks_url="http://127.0.0.1:1/jwks.json",
        content_hash="test-hash",
    )
