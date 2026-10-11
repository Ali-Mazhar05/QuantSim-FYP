from collections.abc import Iterator

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient
from pydantic import BaseModel, SecretStr

from qs_template import ReadinessCheck, ServiceError, ServiceSettings, create_app


def make_settings() -> ServiceSettings:
    return ServiceSettings(
        service_name="sample",
        database_url=SecretStr("postgresql+asyncpg://u:p@localhost/sample"),
        version="1.2.3",
        content_hash="abc123def456",
    )


class Item(BaseModel):
    name: str
    quantity: int


router = APIRouter()


@router.get("/items/{item_id}")
async def get_item(item_id: int) -> dict[str, int]:
    if item_id == 404:
        raise ServiceError(404, "Item not found", f"No item {item_id}.", type_="urn:qs:not-found")
    return {"id": item_id}


@router.post("/items")
async def create_item(item: Item) -> Item:
    return item


@router.get("/boom")
async def boom() -> None:
    raise RuntimeError("database password is hunter2")


async def healthy() -> None:
    return None


async def broken() -> None:
    raise ConnectionError("redis is down")


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app(
        make_settings(),
        routers=[router],
        readiness_checks=[ReadinessCheck("cache", healthy)],
    )
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def test_health_reports_the_build(client: TestClient) -> None:
    response = client.get("/api/sample/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "sample",
        "version": "1.2.3",
        "content_hash": "abc123def456",
    }


def test_routes_live_under_the_service_prefix(client: TestClient) -> None:
    assert client.get("/api/sample/items/7").json() == {"id": 7}
    assert client.get("/items/7").status_code == 404


def test_ready_when_every_check_passes(client: TestClient) -> None:
    response = client.get("/api/sample/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "checks": {"cache": "ok"}}


def test_not_ready_when_a_check_fails() -> None:
    app = create_app(
        make_settings(),
        readiness_checks=[ReadinessCheck("cache", healthy), ReadinessCheck("broker", broken)],
    )
    with TestClient(app) as client:
        response = client.get("/api/sample/ready")

    assert response.status_code == 503
    assert response.json()["checks"] == {"cache": "ok", "broker": "unavailable"}


def test_echoes_a_supplied_request_id(client: TestClient) -> None:
    response = client.get("/api/sample/items/1", headers={"X-Request-ID": "req-42"})

    assert response.headers["X-Request-ID"] == "req-42"


def test_generates_a_request_id_when_none_is_supplied(client: TestClient) -> None:
    response = client.get("/api/sample/items/1")

    assert len(response.headers["X-Request-ID"]) == 32


def test_service_errors_become_problem_details(client: TestClient) -> None:
    response = client.get("/api/sample/items/404", headers={"X-Request-ID": "req-7"})

    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json() == {
        "type": "urn:qs:not-found",
        "title": "Item not found",
        "status": 404,
        "detail": "No item 404.",
        "request_id": "req-7",
    }


def test_invalid_input_lists_every_problem(client: TestClient) -> None:
    response = client.post("/api/sample/items", json={"quantity": "many"})

    assert response.status_code == 422
    body = response.json()
    assert body["title"] == "Invalid request"
    assert {tuple(e["location"]) for e in body["errors"]} == {
        ("body", "name"),
        ("body", "quantity"),
    }


def test_unknown_routes_use_the_same_format(client: TestClient) -> None:
    response = client.get("/api/sample/nowhere")

    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"


def test_unexpected_errors_do_not_leak_details(client: TestClient) -> None:
    response = client.get("/api/sample/boom")

    assert response.status_code == 500
    assert "hunter2" not in response.text
    assert response.json()["title"] == "Internal error"
