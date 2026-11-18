"""Command line of the Risk service image.

python -m qs_risk worker   claim jobs and run their handlers (see jobs.py)
python -m qs_risk relay    publish outbox events to Redpanda
"""

import argparse
import asyncio
import signal
from collections.abc import Callable

from qs_risk.jobs import HANDLERS, job_queue
from qs_risk.settings import RiskSettings
from qs_template import Database
from qs_template.jobs import Worker
from qs_template.kafka import KafkaPublisher
from qs_template.logging import configure_logging
from qs_template.messaging import OutboxRelay


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="qs-risk")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("worker", help="claim jobs and run their handlers")
    commands.add_parser("relay", help="publish outbox events to Redpanda")
    args = parser.parse_args(argv)
    if args.command == "worker":
        asyncio.run(_worker())
    elif args.command == "relay":
        asyncio.run(_relay())


def _on_signals(loop: asyncio.AbstractEventLoop, stop: Callable[[], None]) -> None:
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop)
        except NotImplementedError:  # Windows development machines
            pass


def _settings(process: str) -> RiskSettings:
    settings = RiskSettings()
    configure_logging(
        service=f"{settings.service_name}-{process}",
        environment=settings.environment,
        level=settings.log_level,
    )
    return settings


async def _worker() -> None:
    settings = _settings("worker")
    database = Database(settings)
    worker = Worker(database, job_queue(settings), HANDLERS, poll_seconds=settings.job_poll_seconds)
    _on_signals(asyncio.get_running_loop(), worker.stop)
    try:
        await worker.run()
    finally:
        await database.close()


async def _relay() -> None:
    settings = _settings("relay")
    if not settings.kafka_bootstrap_servers:
        raise SystemExit("QS_KAFKA_BOOTSTRAP_SERVERS is required for the relay")
    database = Database(settings)
    publisher = KafkaPublisher(settings.kafka_bootstrap_servers, client_id="risk-relay")
    await publisher.start()
    relay = OutboxRelay(database, publisher)
    _on_signals(asyncio.get_running_loop(), relay.stop)
    try:
        await relay.run()
    finally:
        await publisher.stop()
        await database.close()
