"""Settings of the Simulation service, on top of the template's (all ``QS_*``)."""

from pydantic import Field, SecretStr

from qs_template import ServiceSettings


class SimulationSettings(ServiceSettings):
    service_name: str = "simulation"

    # Redis for the shared token revocation list
    redis_url: SecretStr

    # Job worker (qs_template.jobs)
    job_lease_seconds: float = Field(default=60.0, gt=0)
    job_max_attempts: int = Field(default=3, ge=1)
    job_poll_seconds: float = Field(default=2.0, gt=0)

    # DEV runs the job worker and outbox relay inside the API process (one container per
    # service); other environments run them in their own containers
    embedded_workers: bool = False

    # Monte Carlo runs (B16, B-NFR-14)
    # Processes that generate shards of a run; 0 means one fewer than the cores, at least one
    shard_workers: int = Field(default=0, ge=0)
    # The most prices (paths x steps x instruments) a run may hold in memory while it is generated:
    # 60 million is about 480 MB of float64, which a laptop-hosted worker can take
    max_run_values: int = Field(default=60_000_000, ge=1)
