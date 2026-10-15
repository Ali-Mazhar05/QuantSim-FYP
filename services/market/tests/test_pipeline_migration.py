"""Migration 0002 adds the item report and removes it again on downgrade."""

import os
import uuid

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from tests.conftest import SERVICE_ROOT, _execute_autocommit, run

pytestmark = pytest.mark.db


async def _has_report_column(url: str) -> bool:
    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection:
            found = await connection.execute(
                text(
                    "SELECT 1 FROM information_schema.columns WHERE table_name = "
                    "'ingestion_run_item' AND column_name = 'report'"
                )
            )
            return found.first() is not None
    finally:
        await engine.dispose()


def test_item_report_migration_round_trips() -> None:
    base = os.environ["TEST_DATABASE_URL"]
    name = f"market_mig_{uuid.uuid4().hex[:12]}"
    run(_execute_autocommit(base, f'CREATE DATABASE "{name}"'))
    url = make_url(base).set(database=name).render_as_string(hide_password=False)
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    try:
        run(_execute_autocommit(url, "CREATE EXTENSION IF NOT EXISTS timescaledb"))
        config = Config(str(SERVICE_ROOT / "alembic.ini"))
        config.set_main_option("script_location", str(SERVICE_ROOT / "migrations"))
        command.upgrade(config, "head")
        assert run(_has_report_column(url))
        command.downgrade(config, "0001")
        assert not run(_has_report_column(url))
        command.upgrade(config, "head")
        assert run(_has_report_column(url))
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
        run(_execute_autocommit(base, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
