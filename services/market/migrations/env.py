"""Alembic environment for market_db, using the async driver the service uses."""

import asyncio
import os

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from qs_market.models import metadata
from qs_template.messaging import messaging_metadata

target_metadata = [metadata, messaging_metadata]


def database_url() -> str:
    url = os.environ.get("DATABASE_URL") or os.environ.get("QS_DATABASE_URL")
    if not url:
        raise SystemExit("set DATABASE_URL (or QS_DATABASE_URL) to run migrations")
    return url


def run_offline() -> None:
    context.configure(url=database_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def _run(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_online() -> None:
    engine = create_async_engine(database_url(), poolclass=pool.NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(_run)
    await engine.dispose()


if context.is_offline_mode():
    run_offline()
else:
    asyncio.run(run_online())
