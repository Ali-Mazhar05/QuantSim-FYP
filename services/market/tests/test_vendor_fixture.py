"""The fixture vendor, the factory and the vendor settings."""

import socket
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from fakeredis import FakeAsyncRedis
from pydantic import SecretStr, ValidationError

from qs_market.settings import MarketSettings
from qs_market.vendor.base import UnknownSymbol
from qs_market.vendor.factory import create_source
from qs_market.vendor.fixture import FixtureSource
from qs_market.vendor.tiingo import TiingoSource

FIXTURES = Path(__file__).parent / "fixtures"


def settings(**overrides: Any) -> MarketSettings:
    values: dict[str, Any] = {
        "database_url": SecretStr("postgresql+asyncpg://u:p@unreachable/db"),
        "redis_url": SecretStr("redis://unused"),
    }
    return MarketSettings(**{**values, **overrides})


async def test_fixture_source_opens_no_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("a network connection was attempted")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    rows = await FixtureSource(FIXTURES).fetch_daily("aapl", date(2024, 1, 2), date(2024, 1, 5))
    assert [r["date"] for r in rows] == ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"]


async def test_fixture_source_unknown_and_unsafe_symbols() -> None:
    source = FixtureSource(FIXTURES)
    for symbol in ("ZZZZ", "../conftest", "a/b"):
        with pytest.raises(UnknownSymbol):
            await source.fetch_daily(symbol, date(2024, 1, 1), date(2024, 1, 2))


def test_vendor_defaults_to_fixture() -> None:
    assert settings().vendor == "fixture"


def test_tiingo_without_a_key_fails_fast() -> None:
    with pytest.raises(ValidationError, match="QS_TIINGO_API_KEY"):
        settings(vendor="tiingo")


def test_reserve_cannot_exceed_the_limit() -> None:
    with pytest.raises(ValidationError, match="RESERVE"):
        settings(tiingo_requests_per_hour=10, tiingo_scheduled_reserve=11)


def test_settings_are_read_from_qs_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QS_VENDOR", "tiingo")
    monkeypatch.setenv("QS_TIINGO_API_KEY", "k-1")
    monkeypatch.setenv("QS_TIINGO_REQUESTS_PER_HOUR", "30")
    monkeypatch.setenv("QS_TIINGO_SCHEDULED_RESERVE", "25")
    loaded = settings()
    assert loaded.vendor == "tiingo"
    assert loaded.tiingo_requests_per_hour == 30
    assert "k-1" not in repr(loaded)


def test_factory_builds_each_source() -> None:
    assert isinstance(create_source(settings(fixture_dir=FIXTURES)), FixtureSource)
    keyed = settings(vendor="tiingo", tiingo_api_key=SecretStr("k"))
    assert isinstance(create_source(keyed, FakeAsyncRedis()), TiingoSource)
    with pytest.raises(ValueError):
        create_source(settings())
    with pytest.raises(ValueError):
        create_source(keyed)
