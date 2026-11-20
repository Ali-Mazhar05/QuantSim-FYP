import os

import pytest
from pydantic import SecretStr

from qs_trading.settings import TradingSettings


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Skip database tests when no database is available (CI always provides one)."""
    if os.environ.get("TEST_DATABASE_URL"):
        return
    skip = pytest.mark.skip(reason="TEST_DATABASE_URL is not set")
    for item in items:
        # The marker itself, not the keyword: tests/db would match every test inside it
        if item.get_closest_marker("db") is not None:
            item.add_marker(skip)


@pytest.fixture
def settings() -> TradingSettings:
    return TradingSettings(
        database_url=SecretStr("postgresql+asyncpg://unused:unused@127.0.0.1:1/unused"),
        redis_url=SecretStr("redis://127.0.0.1:1/0"),
        auth_jwks_url="http://127.0.0.1:1/jwks.json",
        content_hash="test-hash",
    )
