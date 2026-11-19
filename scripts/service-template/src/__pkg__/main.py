"""Builds the __Title__ service application.

``uvicorn --factory __pkg__.main:create`` reads the settings from the environment; tests
call :func:`build_app` with their own pieces. With ``QS_EMBEDDED_WORKERS=true`` (DEV) the
job worker and the outbox relay run inside this process instead of their own containers.
"""

from fastapi import FastAPI

from __pkg__.api import build_routers
from __pkg__.jobs import HANDLERS, job_queue
from __pkg__.settings import __Class__Settings
from qs_template import Database, ReadinessCheck, create_app
from qs_template.auth import Authenticator
from qs_template.background import BackgroundTasks
from qs_template.jobs import Worker
from qs_template.kafka import KafkaPublisher
from qs_template.messaging import OutboxRelay
from qs_template.revocation import RevocationList


def embedded_loops(settings: __Class__Settings, database: Database) -> BackgroundTasks:
    """The worker and relay loops this process runs when embedded mode is on."""
    tasks = BackgroundTasks()
    if not settings.embedded_workers:
        return tasks
    worker = Worker(database, job_queue(settings), HANDLERS, poll_seconds=settings.job_poll_seconds)
    tasks.add("worker", worker.run, worker.stop)
    if settings.kafka_bootstrap_servers:
        servers = settings.kafka_bootstrap_servers
        relays: list[OutboxRelay] = []

        async def relay_loop() -> None:
            # Created here, inside the running loop, so nothing connects before startup
            publisher = KafkaPublisher(servers, client_id="__name__-relay")
            relay = OutboxRelay(database, publisher)
            relays.append(relay)
            await publisher.start()
            try:
                await relay.run()
            finally:
                await publisher.stop()

        def stop_relay() -> None:
            for relay in relays:
                relay.stop()

        tasks.add("relay", relay_loop, stop_relay)
    return tasks


def build_app(
    settings: __Class__Settings,
    *,
    database: Database | None = None,
    revocations: RevocationList | None = None,
    authenticator: Authenticator | None = None,
) -> FastAPI:
    database = database or Database(settings)
    revocations = revocations or RevocationList.from_url(settings.redis_url.get_secret_value())
    auth = authenticator or Authenticator(settings, is_revoked=revocations.is_revoked)
    loops = embedded_loops(settings, database)
    return create_app(
        settings,
        database=database,
        routers=build_routers(auth=auth, database=database),
        readiness_checks=[ReadinessCheck("redis", revocations.ping)],
        on_startup=[loops.start],
        on_shutdown=[loops.stop, revocations.close],
    )


def create() -> FastAPI:
    return build_app(__Class__Settings())
