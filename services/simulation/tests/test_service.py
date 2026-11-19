"""The generated service answers its health check, wires the job queue and knows its
commands. Replace or extend these as the service grows."""

import pytest
from fastapi.testclient import TestClient

from qs_simulation.cli import main
from qs_simulation.jobs import HANDLERS, job_queue
from qs_simulation.main import build_app, embedded_loops
from qs_simulation.models import job
from qs_simulation.settings import SimulationSettings
from qs_template import Database


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


async def test_embedded_mode_runs_the_worker_and_relay_in_process(
    settings: SimulationSettings,
) -> None:
    database = Database(settings)
    assert len(embedded_loops(settings, database)) == 0
    embedded = settings.model_copy(
        update={"embedded_workers": True, "kafka_bootstrap_servers": "127.0.0.1:1"}
    )
    assert len(embedded_loops(embedded, database)) == 2


def test_unknown_command_is_refused() -> None:
    with pytest.raises(SystemExit):
        main(["dance"])
