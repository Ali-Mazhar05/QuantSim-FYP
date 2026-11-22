"""The queue depth an operator reads (B-NFR-13): counts per kind, the oldest wait, expired leases,
and who may read it."""

import uuid
from typing import Any

import pytest

from qs_template.auth import Role
from tests.auth_support import bearer, make_token
from tests.run_support import RunWorld, run_body
from tests.test_runs import complete, submit

pytestmark = pytest.mark.db
QUEUE = "/api/simulation/admin/queue"


async def read(w: RunWorld, role: Role = Role.ADMIN) -> dict[str, Any]:
    response = await w.client.get(QUEUE, headers=bearer(make_token(role)))
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def test_an_empty_queue_is_zero_everywhere(run_world: RunWorld) -> None:
    assert await read(run_world) == {"queued": 0, "running": 0, "kinds": []}


async def test_it_counts_each_kind_by_state_and_times_the_oldest_wait(run_world: RunWorld) -> None:
    basket = await run_world.basket(2)
    await complete(run_world, run_body(basket, n_paths=30, n_steps=3))
    await submit(run_world, run_body(basket, seed=9, n_paths=30, n_steps=3))
    body = await read(run_world)
    assert (body["queued"], body["running"]) == (1, 0)
    [monte_carlo] = [k for k in body["kinds"] if k["kind"] == "monte_carlo"]
    assert (monte_carlo["queued"], monte_carlo["succeeded"], monte_carlo["failed"]) == (1, 1, 0)
    assert monte_carlo["oldest_queued_seconds"] >= 0
    assert monte_carlo["expired_leases"] == 0


async def test_a_job_whose_worker_died_shows_as_an_expired_lease(run_world: RunWorld) -> None:
    basket = await run_world.basket(2)
    queued = await submit(run_world, run_body(basket, n_paths=30, n_steps=3))
    from sqlalchemy import text

    async with run_world.database.transaction() as session:
        await session.execute(
            text(
                "UPDATE job SET status = 'running', lease_owner = 'dead-worker',"
                " lease_expires_at = now() - interval '1 minute' WHERE id = :i"
            ),
            {"i": uuid.UUID(queued["id"])},
        )
    body = await read(run_world)
    assert (body["queued"], body["running"]) == (0, 1)
    [kind] = body["kinds"]
    assert kind["expired_leases"] == 1


@pytest.mark.parametrize("role", [Role.VIEWER, Role.ANALYST, Role.QUANT])
async def test_only_an_administrator_reads_it(run_world: RunWorld, role: Role) -> None:
    response = await run_world.client.get(QUEUE, headers=bearer(make_token(role)))
    assert response.status_code == 403


async def test_anonymous_and_forged_callers_are_refused(run_world: RunWorld) -> None:
    assert (await run_world.client.get(QUEUE)).status_code == 401
    forged = bearer(make_token(Role.ADMIN, forged=True))
    assert (await run_world.client.get(QUEUE, headers=forged)).status_code == 401
