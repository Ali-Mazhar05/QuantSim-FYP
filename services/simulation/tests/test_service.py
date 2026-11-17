"""The generated service answers its health check, wires the job queue and knows its
commands. Replace or extend these as the service grows."""

import pytest
from fastapi.testclient import TestClient

from qs_simulation.cli import main
from qs_simulation.jobs import HANDLERS, job_queue
from qs_simulation.main import build_app
from qs_simulation.models import job
from qs_simulation.settings import SimulationSettings


def test_health_reports_the_build(settings: SimulationSettings) -> None:
    with TestClient(build_app(settings)) as client:
        response = client.get("/api/simulation/health")
    assert response.status_code == 200
    assert response.json()["content_hash"] == "test-hash"


def test_job_queue_uses_the_service_table(settings: SimulationSettings) -> None:
    queue = job_queue(settings)
    assert queue.table is job
    assert queue.lease_seconds == settings.job_lease_seconds
    assert all(callable(handler) for handler in HANDLERS.values())


def test_unknown_command_is_refused() -> None:
    with pytest.raises(SystemExit):
        main(["dance"])
