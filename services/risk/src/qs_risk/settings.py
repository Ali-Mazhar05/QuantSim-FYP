"""Settings of the Risk service, on top of the template's (all ``QS_*``)."""

from pydantic import Field, SecretStr

from qs_template import ServiceSettings


class RiskSettings(ServiceSettings):
    service_name: str = "risk"

    # Redis for the shared token revocation list
    redis_url: SecretStr

    # Job worker (qs_template.jobs)
    job_lease_seconds: float = Field(default=60.0, gt=0)
    job_max_attempts: int = Field(default=3, ge=1)
    job_poll_seconds: float = Field(default=2.0, gt=0)
