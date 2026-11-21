"""A write is committed before its response is sent (read your own writes).

With FastAPI's default dependency scope a request's transaction committed after the
response had gone out, so an admin could invite a user, get 201, and have the very next
request miss that user. Every committing dependency is declared with
``scope="function"``; this test records the order on the wire.
"""

from collections.abc import AsyncIterator, Awaitable, Callable, MutableMapping
from contextlib import asynccontextmanager
from typing import Any

import httpx
import pytest
from fakeredis import FakeAsyncRedis
from sqlalchemy.ext.asyncio import AsyncSession

from qs_platform.limits import RateLimiter
from qs_platform.main import build_app
from qs_template import Database
from qs_template.revocation import RevocationList
from tests.conftest import ADMIN_PASSWORD, bearer, login, make_settings

pytestmark = pytest.mark.db

API = "/api/platform"
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGI = Callable[[MutableMapping[str, Any], Receive, Send], Awaitable[None]]


def record_commits(database: Database, events: list[str], monkeypatch: pytest.MonkeyPatch) -> None:
    """Every transaction of ``database`` (request sessions and audited writers) notes its
    commit."""
    transaction = database.transaction

    @asynccontextmanager
    async def recording() -> AsyncIterator[AsyncSession]:
        async with transaction() as session:
            yield session
        events.append("commit")

    monkeypatch.setattr(database, "transaction", recording)


def record_responses(app: ASGI, events: list[str]) -> ASGI:
    async def wrapped(scope: MutableMapping[str, Any], receive: Receive, send: Send) -> None:
        async def recording_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                events.append("response")
            await send(message)

        await app(scope, receive, recording_send)

    return wrapped


async def test_an_invited_user_is_committed_before_the_201_is_sent(
    database: Database, redis: FakeAsyncRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[str] = []
    app = build_app(
        make_settings(),
        database=database,
        revocations=RevocationList(redis),
        limiter=RateLimiter(redis),
    )
    record_commits(database, events, monkeypatch)
    transport = httpx.ASGITransport(app=record_responses(app, events))
    async with httpx.AsyncClient(transport=transport, base_url="http://platform") as client:
        token = await login(client, "admin", ADMIN_PASSWORD)
        events.clear()
        created = await client.post(
            f"{API}/users",
            json={
                "username": "sara",
                "email": "sara@quantsim.dev",
                "display_name": "Sara",
                "role": "quant",
            },
            headers=bearer(token),
        )
    assert created.status_code == 201, created.text
    assert "response" in events, events
    assert "commit" not in events[events.index("response") :], events
