"""A throwaway trading_db for the database tests, set up the way db-init sets up deployed
environments: an empty database owned by a login role of its own, the timescaledb
extension created by the superuser, and the migrations run as that role."""

import asyncio
import os
import uuid
from collections.abc import Coroutine, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

SERVICE_ROOT = Path(__file__).resolve().parents[2]


def run[T](coroutine: Coroutine[Any, Any, T]) -> T:
    """Run async database code from a synchronous test (Alembic runs its own loop)."""
    return asyncio.run(coroutine)


async def execute_autocommit(url: str, statement: str) -> None:
    engine = create_async_engine(url, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as connection:
            await connection.execute(text(statement))
    finally:
        await engine.dispose()


def alembic_config() -> Config:
    config = Config(str(SERVICE_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(SERVICE_ROOT / "migrations"))
    return config


@contextmanager
def database_url(url: str) -> Iterator[None]:
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous


@dataclass(frozen=True)
class TradingDb:
    app_url: str  # the service's own role, which owns the database and runs migrations
    admin_url: str  # the superuser, on the same database
    role: str


@contextmanager
def fresh_database() -> Iterator[TradingDb]:
    """An empty database owned by a new login role, with the timescaledb extension."""
    base_url = os.environ["TEST_DATABASE_URL"]
    suffix = uuid.uuid4().hex[:12]
    role = f"trading_app_{suffix}"
    name = f"trading_test_{suffix}"
    password = uuid.uuid4().hex
    run(execute_autocommit(base_url, f"CREATE ROLE \"{role}\" LOGIN PASSWORD '{password}'"))
    try:
        run(execute_autocommit(base_url, f'CREATE DATABASE "{name}" OWNER "{role}"'))
        try:
            admin = make_url(base_url).set(database=name)
            app = admin.set(username=role, password=password)
            admin_url = admin.render_as_string(hide_password=False)
            run(execute_autocommit(admin_url, "CREATE EXTENSION IF NOT EXISTS timescaledb"))
            yield TradingDb(app.render_as_string(hide_password=False), admin_url, role)
        finally:
            run(execute_autocommit(base_url, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    finally:
        run(execute_autocommit(base_url, f'DROP ROLE IF EXISTS "{role}"'))


@contextmanager
def migrated_database() -> Iterator[TradingDb]:
    """A fresh database upgraded to the head revision; ``DATABASE_URL`` points at it."""
    with fresh_database() as database, database_url(database.app_url):
        command.upgrade(alembic_config(), "head")
        yield database
