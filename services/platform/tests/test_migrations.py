"""platform_db built by the migrations matches the table definitions exactly (migration
protocol rule 8), including the template's outbox and processed-events tables."""

import asyncio
import os
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import MetaData, text
from sqlalchemy.engine import Connection, make_url
from sqlalchemy.ext.asyncio import create_async_engine

from qs_platform.models import metadata
from qs_template.messaging import messaging_metadata

pytestmark = pytest.mark.db

SERVICE_ROOT = Path(__file__).resolve().parents[1]


async def _autocommit(url: str, statement: str) -> None:
    engine = create_async_engine(url, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as connection:
            await connection.execute(text(statement))
    finally:
        await engine.dispose()


@pytest.fixture(scope="module")
def migrated_url() -> Iterator[str]:
    base_url = os.environ["TEST_DATABASE_URL"]
    name = f"platform_test_{uuid.uuid4().hex[:12]}"
    asyncio.run(_autocommit(base_url, f'CREATE DATABASE "{name}"'))
    url = make_url(base_url).set(database=name).render_as_string(hide_password=False)
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    try:
        config = Config(str(SERVICE_ROOT / "alembic.ini"))
        config.set_main_option("script_location", str(SERVICE_ROOT / "migrations"))
        command.upgrade(config, "head")
        yield url
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
        asyncio.run(_autocommit(base_url, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


def _combined() -> MetaData:
    combined = MetaData()
    for source in (metadata, messaging_metadata):
        for table in source.tables.values():
            table.to_metadata(combined)
    return combined


def _diff(connection: Connection) -> list[Any]:
    def include(obj: Any, name: str | None, type_: str, reflected: bool, compare_to: Any) -> bool:
        # The audit log comes from template SQL rather than a table definition
        return name not in {"audit_log", "audit_log_record"}

    context = MigrationContext.configure(
        connection, opts={"compare_type": True, "include_object": include}
    )
    return list(compare_metadata(context, _combined()))


def test_models_match_the_migrations_exactly(migrated_url: str) -> None:
    async def work() -> list[Any]:
        engine = create_async_engine(migrated_url)
        try:
            async with engine.connect() as connection:
                return await connection.run_sync(_diff)
        finally:
            await engine.dispose()

    assert asyncio.run(work()) == []


def _alembic_config() -> Config:
    config = Config(str(SERVICE_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(SERVICE_ROOT / "migrations"))
    return config


@pytest.fixture
def empty_url() -> Iterator[str]:
    base_url = os.environ["TEST_DATABASE_URL"]
    name = f"platform_test_{uuid.uuid4().hex[:12]}"
    asyncio.run(_autocommit(base_url, f'CREATE DATABASE "{name}"'))
    url = make_url(base_url).set(database=name).render_as_string(hide_password=False)
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    try:
        yield url
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
        asyncio.run(_autocommit(base_url, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


async def _run(url: str, statement: str) -> list[Any]:
    engine = create_async_engine(url)
    try:
        async with engine.begin() as connection:
            result = await connection.execute(text(statement))
            return list(result.all()) if result.returns_rows else []
    finally:
        await engine.dispose()


def test_existing_users_stay_verified_and_approved_through_0003(empty_url: str) -> None:
    config = _alembic_config()
    command.upgrade(config, "0002")
    asyncio.run(
        _run(
            empty_url,
            "INSERT INTO users (username, email, display_name, password_hash, role)"
            " VALUES ('old.user', 'old@example.com', 'Old', 'hash', 'quant')",
        )
    )
    command.upgrade(config, "head")
    rows = asyncio.run(
        _run(
            empty_url,
            "SELECT email_verified_at = created_at, approved_at = created_at FROM users",
        )
    )
    assert rows == [(True, True)]

    # Down and up again leaves the same schema
    command.downgrade(config, "0002")
    command.upgrade(config, "head")


def test_downgrade_below_0003_refuses_while_invited_users_have_no_password(
    empty_url: str,
) -> None:
    config = _alembic_config()
    command.upgrade(config, "head")
    asyncio.run(
        _run(
            empty_url,
            "INSERT INTO users (username, email, display_name, role)"
            " VALUES ('invited', 'invited@example.com', 'Invited', 'viewer')",
        )
    )
    with pytest.raises(RuntimeError, match="no password"):
        command.downgrade(config, "0002")
