"""Choose the vendor from configuration (``QS_VENDOR``)."""

from typing import Any

from qs_market.settings import MarketSettings
from qs_market.vendor.base import PriceSource
from qs_market.vendor.budget import Purpose, RequestBudget
from qs_market.vendor.fixture import FixtureSource
from qs_market.vendor.tiingo import TiingoSource


def create_source(
    settings: MarketSettings,
    redis: Any = None,
    *,
    purpose: Purpose = "scheduled",
) -> PriceSource:
    """The configured source. ``purpose`` decides which share of the budget it may use."""
    if settings.vendor == "fixture":
        if settings.fixture_dir is None:
            raise ValueError("QS_FIXTURE_DIR is required when QS_VENDOR is fixture")
        return FixtureSource(settings.fixture_dir)
    key = settings.tiingo_api_key
    if key is None:
        raise ValueError("QS_TIINGO_API_KEY is required when QS_VENDOR is tiingo")
    if redis is None:
        raise ValueError("a Redis client is required to meter the Tiingo budget")
    budget = RequestBudget(
        redis,
        key,
        limit=settings.tiingo_requests_per_hour,
        reserve_for_scheduled=settings.tiingo_scheduled_reserve,
    )
    return TiingoSource(
        key,
        base_url=settings.tiingo_base_url,
        timeout_seconds=settings.tiingo_timeout_seconds,
        budget=budget,
        purpose=purpose,
    )
