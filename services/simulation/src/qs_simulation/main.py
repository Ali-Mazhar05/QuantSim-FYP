"""Builds the Simulation service application.

``uvicorn --factory qs_simulation.main:create`` reads the settings from the environment; tests
call :func:`build_app` with their own pieces. With ``QS_EMBEDDED_WORKERS=true`` (DEV) the
job worker and the outbox relay run inside this process instead of their own containers.
"""

from collections.abc import Mapping

from fastapi import FastAPI

from qs_simulation.adapters.calibrators import QuantCalibrator
from qs_simulation.api import build_routers
from qs_simulation.calibrations import KIND as CALIBRATE
from qs_simulation.calibrations import make_handler
from qs_simulation.jobs import HANDLERS, job_queue
from qs_simulation.ports import Calibrator, PriceWindowSource
from qs_simulation.settings import SimulationSettings
from qs_template import Database, ReadinessCheck, create_app
from qs_template.auth import Authenticator
from qs_template.background import BackgroundTasks
from qs_template.jobs import Handler, Worker
from qs_template.kafka import KafkaPublisher
from qs_template.messaging import OutboxRelay
from qs_template.revocation import RevocationList


def embedded_loops(
    settings: SimulationSettings, database: Database, handlers: Mapping[str, Handler] = HANDLERS
) -> BackgroundTasks:
    """The worker and relay loops this process runs when embedded mode is on."""
    tasks = BackgroundTasks()
    if not settings.embedded_workers:
        return tasks
    worker = Worker(database, job_queue(settings), handlers, poll_seconds=settings.job_poll_seconds)
    tasks.add("worker", worker.run, worker.stop)
    if settings.kafka_bootstrap_servers:
        servers = settings.kafka_bootstrap_servers
        relays: list[OutboxRelay] = []

        async def relay_loop() -> None:
            # Created here, inside the running loop, so nothing connects before startup
            publisher = KafkaPublisher(servers, client_id="simulation-relay")
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
    settings: SimulationSettings,
    *,
    database: Database | None = None,
    revocations: RevocationList | None = None,
    authenticator: Authenticator | None = None,
    price_source: PriceWindowSource | None = None,
    calibrator: Calibrator | None = None,
) -> FastAPI:
    """``price_source`` is where calibration reads prices from; without one the calibrate job is not
    registered and the route answers 503 (the market client needs K3's service tokens)."""
    database = database or Database(settings)
    revocations = revocations or RevocationList.from_url(settings.redis_url.get_secret_value())
    auth = authenticator or Authenticator(settings, is_revoked=revocations.is_revoked)
    calibrator = calibrator or QuantCalibrator()
    handlers: dict[str, Handler] = dict(HANDLERS)
    if price_source is not None:
        handlers[CALIBRATE] = make_handler(
            database=database, source=price_source, calibrator=calibrator
        )
    loops = embedded_loops(settings, database, handlers)
    return create_app(
        settings,
        database=database,
        routers=build_routers(
            auth=auth,
            database=database,
            queue=job_queue(settings),
            calibrator=calibrator,
            can_calibrate=price_source is not None,
        ),
        readiness_checks=[ReadinessCheck("redis", revocations.ping)],
        on_startup=[loops.start],
        on_shutdown=[loops.stop, revocations.close],
    )


def create() -> FastAPI:
    return build_app(SimulationSettings())
