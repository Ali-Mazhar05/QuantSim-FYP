"""Command line of the Platform service image.

qs-platform serve                 HTTP API on port 8000
qs-platform relay                 publish outbox events to Redpanda, send account emails
                                  and remove stale sign-ups once a day
qs-platform bootstrap-admin       create the first admin if there is none
qs-platform seed-test-users       create or reset test.admin, test.quant, test.analyst and
                                  test.viewer (DEV and TEST only)
qs-platform generate-signing-key  print a new QS_SIGNING_KEY value
"""

import argparse
import asyncio
import os
import signal
import sys
from collections.abc import Awaitable, Callable

import uvicorn

from qs_platform.accounts import AccountService
from qs_platform.keys import SigningKeys, generate_signing_key
from qs_platform.limits import RateLimiter
from qs_platform.mail import MailSender, smtp_transport
from qs_platform.service import UserService, create_first_admin, has_active_admin
from qs_platform.settings import PlatformSettings
from qs_template import Database
from qs_template.kafka import KafkaPublisher
from qs_template.logging import configure_logging, get_logger
from qs_template.messaging import OutboxRelay
from qs_template.revocation import RevocationList

HOUSEKEEPING_INTERVAL_SECONDS = 24 * 3600


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="qs-platform")
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve", help="run the HTTP API")
    serve.add_argument("--port", type=int, default=8000)
    commands.add_parser("relay", help="publish outbox events to Redpanda")
    commands.add_parser("bootstrap-admin", help="create the first admin if there is none")
    commands.add_parser("seed-test-users", help="create or reset the four test accounts")
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
    elif args.command == "seed-test-users":
        sys.exit(asyncio.run(_seed_test_users()))
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
    log = get_logger(__name__)
    sender: MailSender | None = None
    # Gmail needs its account and app password; until both are set mail stays queued
    signs_in = bool(settings.smtp_username and settings.smtp_password)
    if settings.smtp_host and (signs_in or settings.smtp_security == "none"):
        sender = MailSender(database, settings, smtp_transport(settings))
    else:
        log.warning("outgoing mail is not configured; account emails stay queued")
    accounts, closers = _account_service(settings)
    stopping = asyncio.Event()

    def stop() -> None:
        relay.stop()
        if sender:
            sender.stop()
        stopping.set()

    async def housekeeping() -> None:
        while not stopping.is_set():
            try:
                async with database.transaction() as session:
                    await accounts.remove_stale_sign_ups(session)
                if sender:
                    await sender.purge()
            except Exception as exc:  # keep the worker alive; try again tomorrow
                log.error("housekeeping failed", error=str(exc))
            try:
                await asyncio.wait_for(stopping.wait(), timeout=HOUSEKEEPING_INTERVAL_SECONDS)
            except TimeoutError:
                pass

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop)
    try:
        await asyncio.gather(relay.run(), *([sender.run()] if sender else []), housekeeping())
    finally:
        for close in closers:
            await close()
        await publisher.stop()
        await database.close()


def _account_service(
    settings: PlatformSettings,
) -> tuple[AccountService, list[Callable[[], Awaitable[None]]]]:
    revocations = RevocationList.from_url(
        settings.redis_url.get_secret_value(),
        max_token_lifetime_seconds=settings.access_token_ttl_seconds,
    )
    limiter = RateLimiter.from_url(settings.redis_url.get_secret_value())
    keys = SigningKeys(
        settings.signing_key_pem, settings.signing_key_id, settings.retired_public_keys
    )
    users = UserService(settings, keys, revocations)
    return AccountService(settings, users, limiter), [revocations.close, limiter.close]


async def _seed_test_users() -> int:
    """Uses QS_TEST_USERS_PASSWORD (12+ characters) and QS_TEST_USERS_EMAIL (the
    inbox their mail goes to, as name@domain; each account gets name+qs-<role>@domain).
    Refuses to run on ACC and PROD."""
    settings = PlatformSettings()
    configure_logging(
        service=settings.service_name, environment=settings.environment, level=settings.log_level
    )
    log = get_logger(__name__)
    if settings.environment in ("acc", "prod"):
        log.error("test users are for DEV and TEST only", environment=settings.environment)
        return 1
    password = os.environ.get("QS_TEST_USERS_PASSWORD", "")
    email = os.environ.get("QS_TEST_USERS_EMAIL", "alimazhar3005@gmail.com")
    if len(password) < 12:
        log.error("QS_TEST_USERS_PASSWORD must be at least 12 characters")
        return 1
    database = Database(settings)
    accounts, closers = _account_service(settings)
    try:
        async with database.transaction() as session:
            await accounts.seed_test_users(session, password, email)
        log.info("test users ready", users="test.admin test.quant test.analyst test.viewer")
        return 0
    finally:
        for close in closers:
            await close()
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
