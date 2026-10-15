"""Settings of the Market Data service, on top of the template's (all ``QS_*``)."""

from datetime import date
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, SecretStr, field_validator, model_validator

from qs_template import ServiceSettings


class MarketSettings(ServiceSettings):
    service_name: str = "market"

    # Redis for the vendor request budget and the token revocation list
    redis_url: SecretStr

    # Price vendor. "fixture" serves recorded responses and never touches the network.
    vendor: Literal["tiingo", "fixture"] = "fixture"
    fixture_dir: Path | None = None
    tiingo_api_key: SecretStr | None = None
    tiingo_base_url: str = "https://api.tiingo.com"
    # One free key allows 50 requests an hour in all environments together (D12)
    tiingo_requests_per_hour: int = Field(default=45, ge=1)
    # Requests per window that backfill and manual runs may not use (D12)
    tiingo_scheduled_reserve: int = Field(default=40, ge=0)
    tiingo_timeout_seconds: float = Field(default=30.0, gt=0)

    # Ingestion pipeline (worker and run-once)
    ingest_poll_seconds: float = Field(default=5.0, gt=0)
    # Where a new instrument's history starts when a run gives no explicit start
    ingest_backfill_start: date = date(2015, 1, 2)
    ingest_outlier_log_return: float = Field(default=0.405, gt=0)
    ingest_outlier_policy: Literal["flag", "reject"] = "flag"
    # Consecutive vendor failures that open the circuit and defer the rest of the run
    ingest_circuit_failures: int = Field(default=5, ge=1)

    # The scheduler only enqueues runs; it is enabled on TEST only (plan section 3.1).
    # Times are UTC, written HH:MM (D16: the catch-up run is 09:30).
    ingest_scheduler_enabled: bool = False
    ingest_daily_time: str = "22:30"
    ingest_catchup_time: str = "09:30"

    @field_validator("ingest_daily_time", "ingest_catchup_time")
    @classmethod
    def _time_of_day(cls, value: str) -> str:
        hours, separator, minutes = value.partition(":")
        valid = (
            separator
            and len(hours) == len(minutes) == 2
            and hours.isdigit()
            and minutes.isdigit()
            and int(hours) < 24
            and int(minutes) < 60
        )
        if not valid:
            raise ValueError("must be a UTC time of day written HH:MM")
        return value

    @model_validator(mode="after")
    def _vendor_is_usable(self) -> Self:
        if self.vendor == "tiingo" and (
            self.tiingo_api_key is None or not self.tiingo_api_key.get_secret_value()
        ):
            raise ValueError("QS_TIINGO_API_KEY is required when QS_VENDOR is tiingo")
        if self.tiingo_scheduled_reserve > self.tiingo_requests_per_hour:
            raise ValueError("QS_TIINGO_SCHEDULED_RESERVE cannot exceed the hourly limit")
        return self
