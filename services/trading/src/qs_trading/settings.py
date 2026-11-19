"""Settings of the Trading service, on top of the template's (all ``QS_*``)."""

from typing import Self

from pydantic import Field, SecretStr, model_validator

from qs_template import ServiceSettings

DEMO_ALLOWED_IN = frozenset({"local", "dev"})
"""Where ``QS_TRADING_DEMO_ENVIRONMENTS`` may be set: runs against bundled fixture data
must never be mistaken for runs against real market data."""


class TradingSettings(ServiceSettings):
    service_name: str = "trading"

    # Redis for the shared token revocation list
    redis_url: SecretStr

    # Job worker (qs_template.jobs)
    job_lease_seconds: float = Field(default=60.0, gt=0)
    job_max_attempts: int = Field(default=3, ge=1)
    job_poll_seconds: float = Field(default=2.0, gt=0)

    # DEV runs the job worker and outbox relay inside the API process (one container per
    # service); other environments run them in their own containers
    embedded_workers: bool = False

    # LOCAL and DEV only: the engine runs portfolios over the fixture files in this
    # directory (<env_id>.json, see qs_trading.adapters.file_environment) until the market
    # adapters (A17) exist. "bundled" is the demo directory shipped inside the package.
    # Empty: no environment is available and every run fails clearly.
    trading_demo_environments: str = ""

    @model_validator(mode="after")
    def _demo_environments_only_in_dev(self) -> Self:
        if self.trading_demo_environments and self.environment not in DEMO_ALLOWED_IN:
            raise ValueError(
                f"QS_TRADING_DEMO_ENVIRONMENTS is for local and dev only, not {self.environment}"
            )
        return self
