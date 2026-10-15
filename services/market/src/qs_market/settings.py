"""Settings of the Market Data service, on top of the template's (all ``QS_*``)."""

from datetime import date
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, SecretStr, model_validator

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

    @model_validator(mode="after")
    def _vendor_is_usable(self) -> Self:
        if self.vendor == "tiingo" and (
            self.tiingo_api_key is None or not self.tiingo_api_key.get_secret_value()
        ):
            raise ValueError("QS_TIINGO_API_KEY is required when QS_VENDOR is tiingo")
        if self.tiingo_scheduled_reserve > self.tiingo_requests_per_hour:
            raise ValueError("QS_TIINGO_SCHEDULED_RESERVE cannot exceed the hourly limit")
        return self
