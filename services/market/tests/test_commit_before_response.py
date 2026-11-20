"""A write is committed before its response is sent (read your own writes).

With FastAPI's default dependency scope a request's transaction committed after the
response had gone out, so a client could add an instrument, get 201, and have its very
next request (an environment on that instrument) miss it. Every committing dependency
is declared with ``scope="function"``; these tests record the order on the wire.
"""

from collections.abc import AsyncIterator, Awaitable, Callable, MutableMapping
from contextlib import asynccontextmanager
from typing import Any

import httpx
import pytest
from fakeredis import FakeAsyncRedis
from sqlalchemy.ext.asyncio import AsyncSession

from qs_market.main import build_app
from qs_template import Database
from qs_template.auth import Authenticator, Role, StaticKeys
from qs_template.revocation import RevocationList
from tests import instrument_support as support
from tests.instrument_support import API, NEW_INSTRUMENT, bearer, make_settings, make_token

database = support.database
pytestmark = pytest.mark.db

Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGI = Callable[[MutableMapping[str, Any], Receive, Send], Awaitable[None]]


def record_commits(database: Database, events: list[str], monkeypatch: pytest.MonkeyPatch) -> None:
    """Every transaction of ``database`` (request sessions and writers) notes its commit."""
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


@pytest.fixture
async def recorded(
    database: Database, migrated_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[tuple[httpx.AsyncClient, list[str]]]:
    events: list[str] = []
    settings = make_settings(migrated_database_url)
    app = build_app(
        settings,
        database=database,
        revocations=RevocationList(FakeAsyncRedis()),
        authenticator=Authenticator(settings, jwks=StaticKeys(support._jwks())),
    )
    record_commits(database, events, monkeypatch)
    transport = httpx.ASGITransport(app=record_responses(app, events))
    async with httpx.AsyncClient(transport=transport, base_url="http://market") as http:
        yield http, events


def committed_before_response(events: list[str]) -> bool:
    return "response" in events and "commit" not in events[events.index("response") :]


async def test_an_added_instrument_is_committed_before_the_201_is_sent(
    recorded: tuple[httpx.AsyncClient, list[str]],
) -> None:
    client, events = recorded
    admin = bearer(make_token(Role.ADMIN))
    created = await client.post(f"{API}/instruments", json=NEW_INSTRUMENT, headers=admin)
    assert created.status_code == 201, created.text
    assert committed_before_response(events), events


async def test_a_created_environment_is_committed_before_the_201_is_sent(
    recorded: tuple[httpx.AsyncClient, list[str]],
) -> None:
    client, events = recorded
    admin = bearer(make_token(Role.ADMIN))
    added = await client.post(f"{API}/instruments", json=NEW_INSTRUMENT, headers=admin)
    assert added.status_code == 201, added.text
    events.clear()
    body = {
        "name": "Read your writes",
        "type": "historical_replay",
        "universe": "One instrument",
        "instrument_ids": [added.json()["id"]],
        "start_date": "2024-01-02",
        "end_date": "2024-03-28",
        "frequency": "daily",
    }
    created = await client.post(f"{API}/environments", json=body, headers=admin)
    assert created.status_code == 201, created.text
    assert committed_before_response(events), events
