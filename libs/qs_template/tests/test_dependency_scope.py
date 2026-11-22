"""The guard that finds ``yield`` dependencies whose exit code runs after the response."""

from collections.abc import AsyncIterator, Iterator
from functools import partial
from typing import Annotated

import pytest
from fastapi import APIRouter, Depends, FastAPI
from fastapi.exceptions import DependencyScopeError
from pydantic import SecretStr

from qs_template import ServiceSettings, create_app
from qs_template.app import request_scoped_yield_dependencies


async def committing() -> AsyncIterator[str]:
    yield "session"


def sync_committing() -> Iterator[str]:
    yield "session"


async def plain() -> str:
    return "value"


class Unit:
    async def __call__(self) -> AsyncIterator[str]:
        yield "unit"


def toy_app() -> FastAPI:
    router = APIRouter()
    Good = Annotated[str, Depends(committing, scope="function")]
    Bad = Annotated[str, Depends(committing)]

    @router.post("/good")
    async def good(session: Good, value: Annotated[str, Depends(plain)]) -> str:
        return session + value

    @router.post("/bad")
    async def bad(session: Bad) -> str:
        return session

    return create_app(toy_settings(), routers=[router])


def test_reports_only_the_request_scoped_yield_dependency() -> None:
    assert request_scoped_yield_dependencies(toy_app()) == [
        "POST /api/sample/bad: session -> committing"
    ]


def test_finds_nested_sync_partial_callable_and_router_level_dependencies() -> None:
    app = FastAPI()

    async def outer(inner: Annotated[str, Depends(sync_committing)]) -> str:
        return inner

    @app.get("/nested")
    async def nested(value: Annotated[str, Depends(outer)]) -> str:
        return value

    @app.get("/partial")
    async def partial_route(value: Annotated[str, Depends(partial(committing))]) -> str:
        return value

    @app.get("/instance", dependencies=[Depends(Unit())])
    async def instance() -> None:
        return None

    included = APIRouter()

    @included.get("/included")
    async def included_route() -> None:
        return None

    app.include_router(included, prefix="/sub", dependencies=[Depends(committing)])

    assert request_scoped_yield_dependencies(app) == [
        "GET /nested: inner -> sync_committing",
        "GET /partial: value -> partial",
        "GET /instance: <dependencies> -> Unit",
        "GET /sub/included: <dependencies> -> committing",
    ]


def test_a_request_scoped_yield_dependency_cannot_wrap_a_function_scoped_one() -> None:
    """Why every level of a committing chain carries scope="function" (FastAPI's rule)."""
    app = FastAPI()

    async def wrapper(
        session: Annotated[str, Depends(committing, scope="function")],
    ) -> AsyncIterator[str]:
        yield session

    with pytest.raises(DependencyScopeError):

        @app.get("/wrapped")
        async def wrapped(value: Annotated[str, Depends(wrapper)]) -> str:
            return value


def test_the_kit_routes_have_none() -> None:
    assert request_scoped_yield_dependencies(create_app(toy_settings())) == []


def toy_settings() -> ServiceSettings:
    return ServiceSettings(
        service_name="sample",
        database_url=SecretStr("postgresql+asyncpg://u:p@localhost/sample"),
    )
