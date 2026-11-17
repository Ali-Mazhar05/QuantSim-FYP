"""The generated service answers its health check, wires the job queue and knows its
commands. Replace or extend these as the service grows."""

import pytest
from fastapi.testclient import TestClient

from qs_trading.cli import main
from qs_trading.jobs import HANDLERS, job_queue
from qs_trading.main import build_app
from qs_trading.models import job
from qs_trading.settings import TradingSettings


def test_health_reports_the_build(settings: TradingSettings) -> None:
    with TestClient(build_app(settings)) as client:
        response = client.get("/api/trading/health")
    assert response.status_code == 200
    assert response.json()["content_hash"] == "test-hash"


def test_job_queue_uses_the_service_table(settings: TradingSettings) -> None:
    queue = job_queue(settings)
    assert queue.table is job
    assert queue.lease_seconds == settings.job_lease_seconds
    assert all(callable(handler) for handler in HANDLERS.values())


def test_unknown_command_is_refused() -> None:
    with pytest.raises(SystemExit):
        main(["dance"])
