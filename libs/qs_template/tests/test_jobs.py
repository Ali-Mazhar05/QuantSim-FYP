"""K1 acceptance: two workers never claim one job; a killed worker's job is reclaimed
after its lease; a duplicate submit returns the same id."""

import asyncio
import uuid
from collections.abc import Mapping
from typing import Any

import pytest
from sqlalchemy import MetaData, text, update

from qs_template import Database
from qs_template.jobs import (
    IdempotencyConflict,
    Job,
    JobQueue,
    ProgressReporter,
    Worker,
    job_table,
)

metadata = MetaData()
job = job_table(metadata)


@pytest.fixture
async def db(database: Database) -> Database:
    async with database.engine.begin() as connection:
        await connection.run_sync(metadata.create_all)
    return database


async def expire_lease(db: Database, job_id: uuid.UUID) -> None:
    """Simulate a dead worker: its lease is in the past."""
    async with db.transaction() as session:
        await session.execute(
            update(job)
            .where(job.c.id == job_id)
            .values(lease_expires_at=text("now() - interval '1 second'"))
        )


def test_queue_settings_are_checked() -> None:
    with pytest.raises(ValueError):
        JobQueue(job, lease_seconds=0)
    with pytest.raises(ValueError):
        JobQueue(job, max_attempts=0)


@pytest.mark.db
async def test_duplicate_submit_returns_the_same_job(db: Database) -> None:
    queue = JobQueue(job)
    async with db.transaction() as session:
        first = await queue.submit(session, "engine.run", {"p": 1}, idempotency_key="k-1")
        again = await queue.submit(session, "engine.run", {"p": 2}, idempotency_key="k-1")
        other = await queue.submit(session, "engine.run", {"p": 1})
    assert first.created and not again.created
    assert again.id == first.id
    assert other.id != first.id
    async with db.transaction() as session:
        with pytest.raises(IdempotencyConflict):
            await queue.submit(session, "calibrate", idempotency_key="k-1")


@pytest.mark.db
async def test_concurrent_duplicate_submits_create_one_job(db: Database) -> None:
    queue = JobQueue(job)

    async def submit() -> uuid.UUID:
        async with db.transaction() as session:
            return (await queue.submit(session, "engine.run", idempotency_key="same")).id

    ids = await asyncio.gather(*(submit() for _ in range(5)))
    assert len(set(ids)) == 1


@pytest.mark.db
async def test_two_open_claims_never_take_the_same_job(db: Database) -> None:
    queue = JobQueue(job)
    async with db.transaction() as session:
        for i in range(2):
            await queue.submit(session, "engine.run", {"i": i})
    # Both transactions stay open: the first holds its row lock while the second claims
    async with db.transaction() as one, db.transaction() as two:
        a = await queue.claim(one, "worker-a")
        b = await queue.claim(two, "worker-b")
        c = await queue.claim(two, "worker-b")
    assert a is not None and b is not None
    assert a.id != b.id
    assert c is None


@pytest.mark.db
async def test_many_workers_claim_every_job_exactly_once(db: Database) -> None:
    queue = JobQueue(job)
    async with db.transaction() as session:
        submitted = {(await queue.submit(session, "engine.run", {"i": i})).id for i in range(30)}

    async def drain(name: str) -> list[uuid.UUID]:
        taken: list[uuid.UUID] = []
        while True:
            async with db.transaction() as session:
                claimed = await queue.claim(session, name)
            if claimed is None:
                return taken
            taken.append(claimed.id)

    results = await asyncio.gather(*(drain(f"worker-{n}") for n in range(4)))
    taken = [job_id for batch in results for job_id in batch]
    assert len(taken) == len(set(taken)) == 30
    assert set(taken) == submitted


@pytest.mark.db
async def test_a_dead_workers_job_is_reclaimed_and_the_old_owner_is_fenced(db: Database) -> None:
    queue = JobQueue(job)
    async with db.transaction() as session:
        submitted = await queue.submit(session, "engine.run")
    async with db.transaction() as session:
        first = await queue.claim(session, "worker-a")
    assert first is not None and first.attempt == 1

    async with db.transaction() as session:
        assert await queue.claim(session, "worker-b") is None  # lease still held

    await expire_lease(db, submitted.id)
    async with db.transaction() as session:
        second = await queue.claim(session, "worker-b")
    assert second is not None and second.id == submitted.id and second.attempt == 2

    async with db.transaction() as session:
        assert not await queue.heartbeat(session, submitted.id, "worker-a")
        assert not await queue.complete(session, submitted.id, "worker-a")
        assert await queue.fail(session, submitted.id, "worker-a", "late") is None
        assert await queue.heartbeat(session, submitted.id, "worker-b", progress=0.5)
        assert await queue.complete(session, submitted.id, "worker-b", {"hash": "abc"})
        state = await queue.get(session, submitted.id)
    assert state is not None
    assert state.status == "succeeded"
    assert state.progress == 1.0
    assert state.result == {"hash": "abc"}
    assert state.finished_at is not None


@pytest.mark.db
async def test_a_lease_that_expires_on_the_last_attempt_fails_the_job(db: Database) -> None:
    queue = JobQueue(job, max_attempts=1)
    async with db.transaction() as session:
        submitted = await queue.submit(session, "engine.run")
        assert await queue.claim(session, "worker-a") is not None
    await expire_lease(db, submitted.id)
    async with db.transaction() as session:
        assert await queue.claim(session, "worker-b") is None
        state = await queue.get(session, submitted.id)
    assert state is not None and state.status == "failed"
    assert state.error is not None and "lease" in state.error


@pytest.mark.db
async def test_fail_requeues_until_attempts_run_out(db: Database) -> None:
    queue = JobQueue(job, max_attempts=2)
    async with db.transaction() as session:
        submitted = await queue.submit(session, "engine.run")
    statuses = []
    for _ in range(2):
        async with db.transaction() as session:
            claimed = await queue.claim(session, "worker-a")
            assert claimed is not None
            statuses.append(await queue.fail(session, claimed.id, "worker-a", "boom"))
    assert statuses == ["queued", "failed"]
    async with db.transaction() as session:
        assert await queue.claim(session, "worker-a") is None
        state = await queue.get(session, submitted.id)
    assert state is not None and state.error == "boom" and state.attempts == 2


@pytest.mark.db
async def test_claim_only_takes_the_requested_kinds(db: Database) -> None:
    queue = JobQueue(job)
    async with db.transaction() as session:
        await queue.submit(session, "calibrate")
        assert await queue.claim(session, "w", kinds=["engine.run"]) is None
        assert await queue.claim(session, "w", kinds=[]) is None
        claimed = await queue.claim(session, "w", kinds=["calibrate"])
    assert claimed is not None and claimed.kind == "calibrate"


@pytest.mark.db
async def test_worker_runs_handlers_and_records_the_outcome(db: Database) -> None:
    queue = JobQueue(job, max_attempts=1)
    seen: list[dict[str, Any]] = []

    async def ok(job: Job, progress: ProgressReporter) -> Mapping[str, Any]:
        await progress(0.5)
        seen.append(job.payload)
        return {"doubled": job.payload["n"] * 2}

    async def broken(job: Job, progress: ProgressReporter) -> None:
        raise RuntimeError("bad input")

    async with db.transaction() as session:
        good = await queue.submit(session, "ok", {"n": 21})
        bad = await queue.submit(session, "broken")
        ignored = await queue.submit(session, "unknown")

    worker = Worker(db, queue, {"ok": ok, "broken": broken}, worker_id="w-1")
    assert await worker.run_once()
    assert await worker.run_once()
    assert not await worker.run_once()

    async with db.transaction() as session:
        good_state = await queue.get(session, good.id)
        bad_state = await queue.get(session, bad.id)
        ignored_state = await queue.get(session, ignored.id)
    assert seen == [{"n": 21}]
    assert good_state is not None and good_state.status == "succeeded"
    assert good_state.result == {"doubled": 42}
    assert bad_state is not None and bad_state.status == "failed"
    assert bad_state.error == "RuntimeError: bad input"
    assert ignored_state is not None and ignored_state.status == "queued"


@pytest.mark.db
async def test_worker_stops_when_asked(db: Database) -> None:
    worker = Worker(db, JobQueue(job), {}, poll_seconds=0.05)
    task = asyncio.create_task(worker.run())
    await asyncio.sleep(0.1)
    worker.stop()
    await asyncio.wait_for(task, timeout=2)
