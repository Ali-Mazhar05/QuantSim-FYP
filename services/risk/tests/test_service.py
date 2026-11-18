"""The generated service answers its health check, wires the job queue and knows its
commands. Replace or extend these as the service grows."""

import pytest
from fastapi.testclient import TestClient

from qs_risk.cli import main
from qs_risk.jobs import HANDLERS, job_queue
from qs_risk.main import build_app
from qs_risk.models import job
from qs_risk.settings import RiskSettings


def test_health_reports_the_build(settings: RiskSettings) -> None:
    with TestClient(build_app(settings)) as client:
        response = client.get("/api/risk/health")
    assert response.status_code == 200
    assert response.json()["content_hash"] == "test-hash"


def test_job_queue_uses_the_service_table(settings: RiskSettings) -> None:
    queue = job_queue(settings)
    assert queue.table is job
    assert queue.lease_seconds == settings.job_lease_seconds
    assert all(callable(handler) for handler in HANDLERS.values())


def test_unknown_command_is_refused() -> None:
    with pytest.raises(SystemExit):
        main(["dance"])
