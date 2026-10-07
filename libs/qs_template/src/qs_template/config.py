"""Service configuration, read only from the environment (NFR-MNT-001).

Every setting is an environment variable prefixed with ``QS_``. A service subclasses
:class:`ServiceSettings` to add its own settings. Construction fails immediately, with
every problem listed, when a required setting is missing or invalid, so a misconfigured
container never starts half-working.
"""

from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["local", "dev", "test", "acc", "prod"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]


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

    # Token verification (qs_template.auth). The Platform service publishes its public
    # signing keys at the JWKS URL; every other service verifies tokens against them.
    auth_jwks_url: str | None = None
    auth_issuer: str = "quantsim-platform"
    auth_audience: str = "quantsim"
    auth_leeway_seconds: int = Field(default=30, ge=0, le=300)

    @property
    def api_prefix(self) -> str:
        """Every route of a service lives under /api/<service-name>."""
        return f"/api/{self.service_name}"
