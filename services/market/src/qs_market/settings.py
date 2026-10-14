"""Settings of the Market Data service, on top of the template's (all ``QS_*``)."""

from datetime import time
from typing import Literal

from pydantic import Field, SecretStr

from qs_template import ServiceSettings


class MarketSettings(ServiceSettings):
    service_name: str = "market"

    # Redis for the vendor rate limiter and the token revocation list
    redis_url: SecretStr

    # Tiingo end-of-day prices; without a key the scheduler does not start runs
    tiingo_api_key: SecretStr | None = None
    tiingo_base_url: str = "https://api.tiingo.com"
    # Kept below Tiingo's free limits (50 requests per hour, 1000 per day)
    tiingo_requests_per_hour: int = Field(default=45, ge=1)
    vendor_timeout_seconds: float = Field(default=30, gt=0)
    vendor_max_attempts: int = Field(default=4, ge=1, le=10)
    # Consecutive vendor failures in one run before it stops calling the vendor
    circuit_breaker_threshold: int = Field(default=5, ge=1)

    # Ingestion window: re-fetch this many sessions before the last stored one so late
    # vendor corrections are picked up
    lookback_sessions: int = Field(default=5, ge=0, le=60)
    # First date fetched for an instrument with no history yet
    backfill_start: str = "2015-01-02"
    # A daily move larger than this (absolute log return) is flagged as an outlier
    outlier_log_return: float = Field(default=0.405, gt=0)  # about a 50% move
    outlier_policy: Literal["flag", "reject"] = "flag"

    # Scheduled runs, UTC: the daily run after the US close and a catch-up run
    daily_run_at: time = time(22, 30)
    catchup_run_at: time = time(6, 0)
    scheduler_enabled: bool = True
