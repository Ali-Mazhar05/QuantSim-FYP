"""Service configuration, read only from the environment (NFR-MNT-001).

Every setting is an environment variable prefixed with ``QS_``. A service subclasses
:class:`ServiceSettings` to add its own settings. Construction fails immediately, with
every problem listed, when a required setting is missing or invalid, so a misconfigured
container never starts half-working.
"""

from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["local", "dev", "test", "acc", "prod"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]
SEARCH_PATH_PATTERN = r"^[a-z_][a-z0-9_]*(,[a-z_][a-z0-9_]*)*$"


class ServiceSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="QS_", extra="ignore", frozen=True)

    service_name: str = Field(min_length=1, pattern=r"^[a-z][a-z0-9-]*$")
    environment: Environment = "local"
    log_level: LogLevel = "INFO"
    # Build identity, baked into the image by ci/scripts/build-push.sh
    version: str = "0.0.0-local"
    content_hash: str = "local"

    # SQLAlchemy URL of the service's own database, e.g. postgresql+asyncpg://...
    database_url: SecretStr
    db_pool_size: int = Field(default=5, ge=1, le=50)
    db_pool_timeout_seconds: float = Field(default=5.0, gt=0)
    # Schema search path, when a service keeps its tables outside "public"
    db_search_path: str | None = Field(default=None, pattern=SEARCH_PATH_PATTERN)

    # Event backbone (Redpanda, Kafka protocol), e.g. redpanda:9092
    kafka_bootstrap_servers: str | None = None

    # Token verification (qs_template.auth). The Platform service publishes its public
    # signing keys at the JWKS URL; every other service verifies tokens against them.
    auth_jwks_url: str | None = None
    auth_issuer: str = "quantsim-platform"
    auth_audience: str = "quantsim"
    auth_leeway_seconds: int = Field(default=30, ge=0, le=300)

    # Shared DEV-only service token (qs_template.service_client, kit K3): workers send it
    # when calling another service, and services accept it as a read-only service
    # principal. Allowed in local and dev only; replaced by real service tokens before TEST.
    service_token: SecretStr | None = None

    # Real service tokens (ADR 09): a service that calls others gets short-lived tokens
    # from the Platform service with its client id (default: the service name) and
    # secret. Set both the URL and the secret to use them instead of QS_SERVICE_TOKEN.
    service_token_url: str | None = None
    service_client_id: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9-]*$")
    service_client_secret: SecretStr | None = None

    # Websites allowed to call this API from a browser, comma-separated exact origins
    # (scheme://host[:port]). Empty: no cross-site calls are allowed.
    cors_origins: str = ""

    @field_validator("service_token_url", "service_client_secret", mode="before")
    @classmethod
    def _empty_is_unset(cls, value: object) -> object:
        # Compose passes an unset variable as an empty string
        return None if value == "" else value

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip().rstrip("/") for o in self.cors_origins.split(",") if o.strip()]

    @property
    def api_prefix(self) -> str:
        """Every route of a service lives under /api/<service-name>."""
        return f"/api/{self.service_name}"
