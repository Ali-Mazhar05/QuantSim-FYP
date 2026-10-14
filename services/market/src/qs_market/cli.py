"""Command line of the Market Data service image (pipeline commands).

python -m qs_market worker     claim pending ingestion runs and execute them, one at a time
python -m qs_market relay      publish outbox events to Redpanda
python -m qs_market run-once   create and execute one run in this process (demos, fixture
                               vendor); prints the run report as JSON
"""

import argparse
import asyncio
import json
import signal
import sys
import uuid
from datetime import date
from typing import Any

from sqlalchemy import select

from qs_market.models import instrument
from qs_market.pipeline.runner import PipelineConfig, run_next
from qs_market.pipeline.runs import ClaimedRun, RunConflict, create_run
from qs_market.settings import MarketSettings
from qs_market.vendor.base import PriceSource
from qs_market.vendor.factory import create_source
from qs_template import Database
from qs_template.kafka import KafkaPublisher
from qs_template.logging import configure_logging, get_logger
from qs_template.messaging import OutboxRelay


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="qs-market")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("worker", help="execute pending ingestion runs")
    commands.add_parser("relay", help="publish outbox events to Redpanda")
    once = commands.add_parser("run-once", help="create and execute one run in-process")
    once.add_argument(
        "--mode", default="manual", choices=["daily", "catchup", "manual", "backfill"]
    )
    once.add_argument("--start", type=date.fromisoformat)
    once.add_argument("--end", type=date.fromisoformat)
    once.add_argument("--symbol", action="append", help="limit to a symbol (repeatable)")
    args = parser.parse_args(argv)

    if args.command == "worker":
        asyncio.run(_worker())
    elif args.command == "relay":
        asyncio.run(_relay())
    elif args.command == "run-once":
        sys.exit(asyncio.run(_run_once(args.mode, args.start, args.end, args.symbol)))


def _config(settings: MarketSettings) -> PipelineConfig:
    return PipelineConfig(
        backfill_start=settings.ingest_backfill_start,
        outlier_log_return=settings.ingest_outlier_log_return,
        outlier_policy=settings.ingest_outlier_policy,
        circuit_failures=settings.ingest_circuit_failures,
    )


def _on_signals(loop: asyncio.AbstractEventLoop, handler: Any) -> None:
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, handler)
        except NotImplementedError:  # Windows event loops; the containers run on Linux
            return


def _redis(settings: MarketSettings) -> Any:
    from redis.asyncio import Redis

    return Redis.from_url(settings.redis_url.get_secret_value())


def _source_factory(settings: MarketSettings, redis: Any) -> Any:
    def make(run: ClaimedRun) -> PriceSource:
        # Backfill and manual runs may only use the unreserved share of the budget
        if run.mode in ("daily", "catchup"):
            return create_source(settings, redis, purpose="scheduled")
        return create_source(settings, redis, purpose="backfill")

    return make


async def _worker() -> None:
    settings = MarketSettings()
    configure_logging(
        service=f"{settings.service_name}-worker",
        environment=settings.environment,
        level=settings.log_level,
    )
    log = get_logger(__name__)
    database = Database(settings)
    redis = _redis(settings)
    stopping = asyncio.Event()
    loop = asyncio.get_running_loop()
    _on_signals(loop, stopping.set)
    make_source = _source_factory(settings, redis)
    config = _config(settings)
    try:
        while not stopping.is_set():
            try:
                outcome = await run_next(database, make_source, config)
            except Exception as exc:  # keep the worker alive; the run is recovered later
                log.error("worker iteration failed", error=str(exc))
                outcome = None
            if outcome is not None:
                continue  # more runs may be waiting
            try:
                await asyncio.wait_for(stopping.wait(), timeout=settings.ingest_poll_seconds)
            except TimeoutError:
                pass
    finally:
        await redis.aclose()
        await database.close()


async def _relay() -> None:
    settings = MarketSettings()
    configure_logging(
        service=f"{settings.service_name}-relay",
        environment=settings.environment,
        level=settings.log_level,
    )
    if not settings.kafka_bootstrap_servers:
        raise SystemExit("QS_KAFKA_BOOTSTRAP_SERVERS is required for the relay")
    database = Database(settings)
    publisher = KafkaPublisher(settings.kafka_bootstrap_servers, client_id="market-relay")
    await publisher.start()
    relay = OutboxRelay(database, publisher)
    loop = asyncio.get_running_loop()
    _on_signals(loop, relay.stop)
    try:
        await relay.run()
    finally:
        await publisher.stop()
        await database.close()


async def _run_once(
    mode: str, start: date | None, end: date | None, symbols: list[str] | None
) -> int:
    settings = MarketSettings()
    configure_logging(
        service=settings.service_name, environment=settings.environment, level=settings.log_level
    )
    database = Database(settings)
    redis = _redis(settings)
    try:
        ids: list[uuid.UUID] | None = None
        async with database.transaction() as session:
            if symbols:
                ids = list(
                    (
                        await session.execute(
                            select(instrument.c.id).where(
                                instrument.c.symbol.in_([s.upper() for s in symbols])
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
            try:
                await create_run(
                    session,
                    mode=mode,
                    window=(start, end) if start or end else None,
                    instrument_ids=ids,
                    idempotency_key=None,
                    requested_by="cli",
                    vendor=settings.vendor,
                )
            except RunConflict as exc:
                print(f"refused: {exc}", file=sys.stderr)
                return 2
        outcome = await run_next(database, _source_factory(settings, redis), _config(settings))
        if outcome is None:
            print("another worker holds the lock; the run stays queued", file=sys.stderr)
            return 3
        print(json.dumps({"status": outcome.status, "error": outcome.error, **outcome.report}))
        return 0 if outcome.status in ("succeeded", "partially_succeeded") else 1
    finally:
        await redis.aclose()
        await database.close()
