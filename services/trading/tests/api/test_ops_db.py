"""A-NFR-14 on a real trading_db, wired as deployed: GET /ops/metrics reports the queue
depth, the job durations and the outbox backlog before and after the worker runs a
portfolio, and the run's log lines carry its job and portfolio ids. On a database of its
own, so the worker claims only this test's job and the counts are exact."""

import shutil
import sys
from collections.abc import MutableMapping
from pathlib import Path
from typing import Any

import pytest
import structlog
from api_support import API, MOMENTUM, as_role, client_for, db_app, make_settings, portfolio_body
from structlog.contextvars import merge_contextvars
from structlog.testing import LogCapture

from qs_template import Database
from qs_template.auth import Role
from qs_template.jobs import Worker
from qs_trading import jobs
from qs_trading.adapters.file_environment import file_environments
from qs_trading.jobs import ENGINE_RUN, build_handlers, job_queue

# The database helpers live beside the other database tests
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "db"))
from trading_db_support import migrated_database, run

pytestmark = pytest.mark.db

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/environments/two_symbols_10_sessions.json"
ENV_ID = "5d0c6c1e-7a14-4a14-8a14-000000000001"
OPS = f"{API}/ops/metrics"


def test_ops_metrics_follow_a_worker_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    shutil.copyfile(FIXTURE, tmp_path / f"{ENV_ID}.json")
    capture = LogCapture()
    monkeypatch.setattr(
        jobs, "log", structlog.wrap_logger(None, processors=[merge_contextvars, capture])
    )
    lines: list[MutableMapping[str, Any]] = capture.entries

    with migrated_database() as own:

        async def scenario() -> None:
            settings = make_settings(own.app_url)
            database = Database(settings)
            admin, quant = as_role(Role.ADMIN), as_role(Role.QUANT)
            try:
                async with client_for(db_app(database, settings)) as http:
                    empty = (await http.get(OPS, headers=admin)).json()
                    assert empty["queue"] == {
                        "kind": ENGINE_RUN,
                        "queued": 0,
                        "running": 0,
                        "succeeded": 0,
                        "failed": 0,
                        "oldest_queued_seconds": None,
                    }
                    assert empty["durations"]["count"] == 0
                    assert empty["outbox"] == {"pending": 0, "oldest_pending_seconds": None}

                    made = await http.post(f"{API}/strategies", json=MOMENTUM, headers=quant)
                    body = portfolio_body(made.json()["id"], replay_environment_id=ENV_ID)
                    created = await http.post(f"{API}/portfolios", json=body, headers=quant)
                    portfolio_id = created.json()["id"]
                    submitted = await http.post(
                        f"{API}/portfolios/{portfolio_id}/runs", headers=quant
                    )
                    assert submitted.status_code == 202, submitted.text
                    job_id = submitted.json()["job_id"]

                    queued = (await http.get(OPS, headers=admin)).json()
                    assert queued["queue"]["queued"] == 1
                    assert queued["queue"]["oldest_queued_seconds"] >= 0

                    handlers = build_handlers(database, file_environments(tmp_path))
                    worker = Worker(database, job_queue(settings), handlers)
                    assert await worker.run_once()

                    done = await http.get(OPS, headers=admin, params={"recent": 10})
                    assert done.status_code == 200, done.text
                    after = done.json()
            finally:
                await database.close()

            assert after["queue"]["queued"] == 0 and after["queue"]["running"] == 0
            assert after["queue"]["succeeded"] == 1 and after["queue"]["failed"] == 0
            assert after["queue"]["oldest_queued_seconds"] is None
            durations = after["durations"]
            assert (durations["window"], durations["count"]) == (10, 1)
            assert 0 <= durations["p50_seconds"] == durations["p95_seconds"]
            assert durations["p95_seconds"] == durations["max_seconds"]
            # No relay runs here, so the run's events wait in the outbox
            assert after["outbox"]["pending"] > 0
            assert after["outbox"]["oldest_pending_seconds"] >= 0

            ids = {"job_id": job_id, "portfolio_id": portfolio_id}
            assert [line["event"] for line in lines] == ["engine run started", "engine run ended"]
            for line in lines:
                assert line.items() >= ids.items(), line
            assert lines[-1]["outcome"] == "completed"
            assert lines[-1]["duration_seconds"] >= 0

        run(scenario())
