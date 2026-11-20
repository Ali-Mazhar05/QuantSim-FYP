"""A write is committed before its response is sent (read your own writes).

With FastAPI's default dependency scope the request session committed after the response
had gone out, so a client could create a strategy, get 201, and have its very next request
(creating a portfolio on it) answered "no strategy has this id". The DEV live check hit
exactly that.
"""

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, MutableMapping
from typing import Any

from api_support import FakeStore, as_role, authenticator, make_settings
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from qs_template import Database, create_app
from qs_template.auth import Role
from qs_trading.api import build_routers
from qs_trading.api_store import TradingStore

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]


class RecordingDatabase(Database):
    """A database whose request session records the moment it commits."""

    def __init__(self, events: list[str]) -> None:
        super().__init__(make_settings())
        self.events = events

    async def session(self) -> AsyncIterator[AsyncSession]:
        async with self.transaction() as session:
            yield session
        self.events.append("commit")


def recording_app(events: list[str]) -> FastAPI:
    settings = make_settings()
    database = RecordingDatabase(events)
    store = FakeStore()

    def factory(_: AsyncSession) -> TradingStore:
        return store

    app = create_app(
        settings,
        database=database,
        routers=build_routers(auth=authenticator(settings), database=database, store=factory),
    )
    inner = app.build_middleware_stack()

    async def record_response(scope: Scope, receive: Receive, send: Send) -> None:
        async def recording_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                events.append("response")
            await send(message)

        await inner(scope, receive, recording_send)

    app.middleware_stack = record_response
    return app


def test_a_created_strategy_is_committed_before_the_201_is_sent() -> None:
    events: list[str] = []
    client = TestClient(recording_app(events))
    response = client.post(
        "/api/trading/strategies",
        headers=as_role(Role.QUANT, user_id=uuid.uuid4()),
        json={"name": "read your writes", "kind": "buy_and_hold", "params": {}},
    )
    assert response.status_code == 201, response.text
    assert events.index("commit") < events.index("response"), events
