"""Command line of the Platform service image.

qs-platform serve                 HTTP API on port 8000
qs-platform relay                 publish outbox events to Redpanda
qs-platform bootstrap-admin       create the first admin if there is none
qs-platform generate-signing-key  print a new QS_SIGNING_KEY value
"""

import argparse
import asyncio
import os
import signal
import sys

import uvicorn

from qs_platform.keys import generate_signing_key
from qs_platform.service import create_first_admin, has_active_admin
from qs_platform.settings import PlatformSettings
from qs_template import Database
from qs_template.kafka import KafkaPublisher
from qs_template.logging import configure_logging, get_logger
from qs_template.messaging import OutboxRelay


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="qs-platform")
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve", help="run the HTTP API")
    serve.add_argument("--port", type=int, default=8000)
    commands.add_parser("relay", help="publish outbox events to Redpanda")
    commands.add_parser("bootstrap-admin", help="create the first admin if there is none")
    commands.add_parser("generate-signing-key", help="print a new QS_SIGNING_KEY value")
    args = parser.parse_args(argv)

    if args.command == "serve":
        uvicorn.run(
            "qs_platform.main:create",
            factory=True,
            host="0.0.0.0",  # noqa: S104 - inside a container, published by the gateway
            port=args.port,
            proxy_headers=True,
            log_config=None,
        )
    elif args.command == "relay":
        asyncio.run(_relay())
    elif args.command == "bootstrap-admin":
        sys.exit(asyncio.run(_bootstrap_admin()))
    elif args.command == "generate-signing-key":
        print(generate_signing_key())


async def _relay() -> None:
    settings = PlatformSettings()
    configure_logging(
        service=f"{settings.service_name}-relay",
        environment=settings.environment,
        level=settings.log_level,
    )
    if not settings.kafka_bootstrap_servers:
        raise SystemExit("QS_KAFKA_BOOTSTRAP_SERVERS is required for the relay")
    database = Database(settings)
    publisher = KafkaPublisher(settings.kafka_bootstrap_servers, client_id="platform-relay")
    await publisher.start()
    relay = OutboxRelay(database, publisher)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, relay.stop)
    try:
        await relay.run()
    finally:
        await publisher.stop()
        await database.close()


async def _bootstrap_admin() -> int:
    """Uses QS_BOOTSTRAP_ADMIN_USERNAME, _EMAIL and _PASSWORD; does nothing once any
    active admin exists, so it is safe to run on every deploy."""
    settings = PlatformSettings()
    configure_logging(
        service=settings.service_name, environment=settings.environment, level=settings.log_level
    )
    log = get_logger(__name__)
    username = os.environ.get("QS_BOOTSTRAP_ADMIN_USERNAME", "admin")
    email = os.environ.get("QS_BOOTSTRAP_ADMIN_EMAIL", "admin@quantsim.dev")
    password = os.environ.get("QS_BOOTSTRAP_ADMIN_PASSWORD", "")
    database = Database(settings)
    try:
        async with database.transaction() as session:
            if await has_active_admin(session):
                log.info("an active admin already exists; nothing to do")
                return 0
            if len(password) < 12:
                log.error("QS_BOOTSTRAP_ADMIN_PASSWORD must be at least 12 characters")
                return 1
            await create_first_admin(session, username=username, email=email, password=password)
        log.info("first admin created", user=username)
        return 0
    finally:
        await database.close()
