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
    # LOCAL and DEV only: mounts the stand-in for Lane B's feeds (qs_trading.demo.feeds) at
    # /demo-feeds, serving the recorded contract fixtures, until B12 serves the real ones
    trading_demo_feeds: bool = False

    # The market feeds (task A17): base URLs of the market and simulation services, e.g.
    # "http://market:8000". When one is set, portfolios on that kind of environment (replay
    # or simulation path) are read over HTTP; when empty, the demo fixtures above or none.
    trading_market_url: str = ""
    trading_simulation_url: str = ""
    # Timeout of one feed request, and how long the engine's per-session fingerprint check
    # is answered from memory (see qs_trading.adapters.http_environment)
    trading_feed_timeout_seconds: float = Field(default=10.0, gt=0)
    trading_fingerprint_cache_seconds: float = Field(default=30.0, ge=0)

    # The service token settings (QS_SERVICE_TOKEN_URL, QS_SERVICE_CLIENT_SECRET, and the DEV
    # QS_SERVICE_TOKEN) are declared by the kit's ServiceSettings (K3, ADR 09) and read by
    # qs_trading.jobs.service_tokens. Never logged.

    @model_validator(mode="after")
    def _demo_environments_only_in_dev(self) -> Self:
        if self.trading_demo_environments and self.environment not in DEMO_ALLOWED_IN:
            raise ValueError(
                f"QS_TRADING_DEMO_ENVIRONMENTS is for local and dev only, not {self.environment}"
            )
        return self

    @model_validator(mode="after")
    def _demo_feeds_only_in_dev(self) -> Self:
        if self.trading_demo_feeds and self.environment not in DEMO_ALLOWED_IN:
            raise ValueError(
                f"QS_TRADING_DEMO_FEEDS is for local and dev only, not {self.environment}"
            )
        return self

    @model_validator(mode="after")
    def _service_token_only_in_dev(self) -> Self:
        # the same rule as K3's StaticServiceToken: the shared token never reaches TEST
        if self.service_token is not None and self.environment not in DEMO_ALLOWED_IN:
            raise ValueError(f"QS_SERVICE_TOKEN is for local and dev only, not {self.environment}")
        return self
