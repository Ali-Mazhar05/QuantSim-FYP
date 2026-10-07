"""Async database access for a service's own database (NFR-MNT-002).

One :class:`Database` per process owns the connection pool. Request handlers get a
session through :meth:`Database.session`, which commits when the handler returns and
rolls back when it raises, so a state change and the events written with it (outbox)
always commit together.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from qs_template.config import ServiceSettings


class Database:
    def __init__(self, settings: ServiceSettings) -> None:
        self.engine: AsyncEngine = create_async_engine(
            settings.database_url.get_secret_value(),
            pool_size=settings.db_pool_size,
            pool_timeout=settings.db_pool_timeout_seconds,
            pool_pre_ping=True,
            connect_args={"server_settings": {"application_name": settings.service_name}},
        )
        self._sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[AsyncSession]:
        """A session whose work commits on success and rolls back on any error."""
        async with self._sessions() as session, session.begin():
            yield session

    async def session(self) -> AsyncIterator[AsyncSession]:
        """FastAPI dependency: ``session: AsyncSession = Depends(db.session)``."""
        async with self.transaction() as session:
            yield session

    async def ping(self) -> None:
        async with self.engine.connect() as connection:
            await connection.execute(text("SELECT 1"))

    async def close(self) -> None:
        await self.engine.dispose()
