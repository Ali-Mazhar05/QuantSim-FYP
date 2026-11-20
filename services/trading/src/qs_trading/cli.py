"""Command line of the Trading service image.

python -m qs_trading worker                       claim jobs and run their handlers (see jobs.py)
python -m qs_trading relay                        publish outbox events to Redpanda
python -m qs_trading verify <portfolio_id>        verify the hash chain of a portfolio's log
python -m qs_trading rebuild <portfolio_id> [--apply]
                                                  rebuild its projections from the log

``verify`` and ``rebuild`` print their report as JSON. Exit codes: 0 the chain is intact
(``verify``) or the projections are identical or were replaced (``rebuild``); 1 the
projections differ (``rebuild`` without ``--apply``); 2 the chain is broken; 3 there is no
such portfolio.
"""

import argparse
import asyncio
import json
import signal
import uuid
from collections.abc import Callable

from qs_template import Database
from qs_template.jobs import Worker
from qs_template.kafka import KafkaPublisher
from qs_template.logging import configure_logging
from qs_template.messaging import OutboxRelay
from qs_trading.engine.store import PortfolioNotFound
from qs_trading.jobs import build_handlers, environment_factory, job_queue
from qs_trading.projections.rebuild import ChainBroken, rebuild_portfolio, verify_portfolio
from qs_trading.settings import TradingSettings

EXIT_DIFFERS = 1
EXIT_BROKEN = 2
EXIT_NOT_FOUND = 3


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="qs-trading")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("worker", help="claim jobs and run their handlers")
    commands.add_parser("relay", help="publish outbox events to Redpanda")
    verify = commands.add_parser("verify", help="verify the hash chain of a portfolio's log")
    verify.add_argument("portfolio_id", type=uuid.UUID)
    rebuild = commands.add_parser("rebuild", help="rebuild a portfolio's projections")
    rebuild.add_argument("portfolio_id", type=uuid.UUID)
    rebuild.add_argument(
        "--apply", action="store_true", help="replace differing projections with the rebuilt rows"
    )
    args = parser.parse_args(argv)
    if args.command == "worker":
        asyncio.run(_worker())
    elif args.command == "relay":
        asyncio.run(_relay())
    elif args.command == "verify":
        raise SystemExit(asyncio.run(_verify(args.portfolio_id)))
    elif args.command == "rebuild":
        raise SystemExit(asyncio.run(_rebuild(args.portfolio_id, apply=args.apply)))


def _on_signals(loop: asyncio.AbstractEventLoop, stop: Callable[[], None]) -> None:
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop)
        except NotImplementedError:  # Windows development machines
            pass


def _settings(process: str) -> TradingSettings:
    settings = TradingSettings()
    configure_logging(
        service=f"{settings.service_name}-{process}",
        environment=settings.environment,
        level=settings.log_level,
    )
    return settings


async def _worker() -> None:
    settings = _settings("worker")
    database = Database(settings)
    worker = Worker(
        database,
        job_queue(settings),
        build_handlers(database, environment_factory(settings)),
        poll_seconds=settings.job_poll_seconds,
    )
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
    publisher = KafkaPublisher(settings.kafka_bootstrap_servers, client_id="trading-relay")
    await publisher.start()
    relay = OutboxRelay(database, publisher)
    _on_signals(asyncio.get_running_loop(), relay.stop)
    try:
        await relay.run()
    finally:
        await publisher.stop()
        await database.close()


def _print(document: object) -> None:
    print(json.dumps(document, indent=2))


async def _verify(portfolio_id: uuid.UUID) -> int:
    database = Database(_settings("verify"))
    try:
        async with database.transaction() as session:
            report = await verify_portfolio(session, portfolio_id)
    except PortfolioNotFound:
        _print({"portfolio_id": str(portfolio_id), "error": "portfolio not found"})
        return EXIT_NOT_FOUND
    finally:
        await database.close()
    _print(report.to_json())
    return 0 if report.valid else EXIT_BROKEN


async def _rebuild(portfolio_id: uuid.UUID, *, apply: bool) -> int:
    database = Database(_settings("rebuild"))
    try:
        async with database.transaction() as session:
            result = await rebuild_portfolio(session, portfolio_id, apply=apply)
    except PortfolioNotFound:
        _print({"portfolio_id": str(portfolio_id), "error": "portfolio not found"})
        return EXIT_NOT_FOUND
    except ChainBroken as broken:
        _print({**broken.report.to_json(), "error": str(broken)})
        return EXIT_BROKEN
    finally:
        await database.close()
    _print(result.to_json())
    return 0 if result.identical or result.applied else EXIT_DIFFERS
