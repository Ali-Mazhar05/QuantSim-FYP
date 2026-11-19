"""On a real trading_db, wired as deployed: a second run of a portfolio is refused with 409
while its first is queued (also when the submits race) and accepted once it has finished,
and only a strategy's owner or an admin may edit it. Each test has a database of its own,
so the worker claims only the jobs the test made."""

import asyncio
import shutil
import sys
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path

import httpx
import pytest
from api_support import API, MOMENTUM, as_role, client_for, db_app, make_settings, portfolio_body

from qs_template import Database
from qs_template.auth import Role
from qs_template.jobs import Worker
from qs_trading.adapters.file_environment import file_environments
from qs_trading.jobs import build_handlers, job_queue

# The database helpers live beside the other database tests
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "db"))
from trading_db_support import migrated_database, run

pytestmark = pytest.mark.db

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/environments/two_symbols_10_sessions.json"
ENV_ID = "5d0c6c1e-7a14-4a14-8a14-000000000001"

Scenario = Callable[[httpx.AsyncClient, Database], Awaitable[None]]


def serve_fresh(scenario: Scenario) -> None:
    """Run ``scenario`` against the deployed app on a database of its own."""
    with migrated_database() as trading_db:

        async def main() -> None:
            settings = make_settings(trading_db.app_url)
            database = Database(settings)
            try:
                async with client_for(db_app(database, settings)) as http:
                    await scenario(http, database)
            finally:
                await database.close()

        run(main())


async def _portfolio(http: httpx.AsyncClient) -> str:
    quant = as_role(Role.QUANT)
    strategy = await http.post(f"{API}/strategies", json=MOMENTUM, headers=quant)
    assert strategy.status_code == 201, strategy.text
    created = await http.post(
        f"{API}/portfolios",
        json=portfolio_body(strategy.json()["id"], replay_environment_id=ENV_ID),
        headers=quant,
    )
    assert created.status_code == 201, created.text
    portfolio_id: str = created.json()["id"]
    return portfolio_id


def test_a_second_key_is_409_while_queued_and_accepted_after_the_run(tmp_path: Path) -> None:
    shutil.copyfile(FIXTURE, tmp_path / f"{ENV_ID}.json")

    async def scenario(http: httpx.AsyncClient, database: Database) -> None:
        quant = as_role(Role.QUANT)
        runs = f"{API}/portfolios/{await _portfolio(http)}/runs"
        first = await http.post(runs, headers={**quant, "Idempotency-Key": "first"})
        assert first.status_code == 202, first.text
        job_id = first.json()["job_id"]

        refused = await http.post(runs, headers={**quant, "Idempotency-Key": "second"})
        assert refused.status_code == 409, refused.text
        assert refused.json()["type"] == "urn:quantsim:problem:run-in-progress"
        assert refused.json()["job_id"] == job_id
        same = await http.post(runs, headers={**quant, "Idempotency-Key": "first"})
        assert same.status_code == 202 and same.json()["job_id"] == job_id

        settings = make_settings()
        worker = Worker(
            database, job_queue(settings), build_handlers(database, file_environments(tmp_path))
        )
        assert await worker.run_once()
        done = (await http.get(f"{runs}/{job_id}", headers=quant)).json()
        assert done["status"] == "succeeded", done["error"]

        accepted = await http.post(runs, headers={**quant, "Idempotency-Key": "second"})
        assert accepted.status_code == 202, accepted.text
        assert accepted.json()["created"] is True and accepted.json()["job_id"] != job_id

    serve_fresh(scenario)


def test_a_permanently_failed_run_frees_the_portfolio_for_a_new_key(tmp_path: Path) -> None:
    # No fixture in tmp_path: the run fails for good on its first attempt
    async def scenario(http: httpx.AsyncClient, database: Database) -> None:
        quant = as_role(Role.QUANT)
        runs = f"{API}/portfolios/{await _portfolio(http)}/runs"
        first = await http.post(runs, headers={**quant, "Idempotency-Key": "first"})
        job_id = first.json()["job_id"]
        worker = Worker(
            database,
            job_queue(make_settings()),
            build_handlers(database, file_environments(tmp_path)),
        )
        assert await worker.run_once()
        failed = (await http.get(f"{runs}/{job_id}", headers=quant)).json()
        assert (failed["status"], failed["attempts"]) == ("failed", 1)
        assert failed["error"].startswith("FixtureError: ")

        again = await http.post(runs, headers={**quant, "Idempotency-Key": "second"})
        assert again.status_code == 202, again.text

    serve_fresh(scenario)


def test_racing_submits_with_different_keys_queue_exactly_one_run() -> None:
    async def scenario(http: httpx.AsyncClient, database: Database) -> None:
        quant = as_role(Role.QUANT)
        runs = f"{API}/portfolios/{await _portfolio(http)}/runs"
        answers = await asyncio.gather(
            *(http.post(runs, headers={**quant, "Idempotency-Key": f"race-{n}"}) for n in range(4))
        )
        codes = sorted(a.status_code for a in answers)
        assert codes == [202, 409, 409, 409], [a.text for a in answers]
        winner = next(a for a in answers if a.status_code == 202).json()["job_id"]
        assert all(a.json()["job_id"] == winner for a in answers)

    serve_fresh(scenario)


def test_only_the_owner_or_an_admin_edits_a_strategy() -> None:
    async def scenario(http: httpx.AsyncClient, database: Database) -> None:
        owner = uuid.uuid4()
        mine = as_role(Role.QUANT, user_id=owner)
        created = await http.post(f"{API}/strategies", json=MOMENTUM, headers=mine)
        assert created.status_code == 201, created.text
        url = f"{API}/strategies/{created.json()['id']}"
        edit = {**MOMENTUM, "name": "Edited"}

        refused = await http.put(url, json=edit, headers=as_role(Role.QUANT))
        assert refused.status_code == 403, refused.text
        assert refused.json()["type"] == "urn:quantsim:problem:forbidden"
        unchanged = await http.get(url, headers=as_role(Role.VIEWER))
        assert unchanged.status_code == 200 and unchanged.json()["name"] == MOMENTUM["name"]

        by_owner = await http.put(url, json=edit, headers=mine)
        assert by_owner.status_code == 200, by_owner.text
        by_admin = await http.put(url, json={**edit, "name": "Admin"}, headers=as_role(Role.ADMIN))
        assert by_admin.status_code == 200, by_admin.text
        assert by_admin.json()["owner_id"] == str(owner)

    serve_fresh(scenario)
