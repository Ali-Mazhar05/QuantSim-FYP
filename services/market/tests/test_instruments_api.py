"""Authorization and validation of the instrument routes."""

import uuid
from typing import Any

import httpx
import pytest
from fakeredis import FakeAsyncRedis

from qs_market.main import build_app
from qs_template.auth import Role
from qs_template.revocation import RevocationList
from tests import instrument_support as support
from tests.instrument_support import (
    API,
    NEW_INSTRUMENT,
    bearer,
    make_settings,
    make_token,
)

client = support.client
database = support.database
pytestmark = pytest.mark.db

EVERYONE = "everyone"  # no token needed
ALL_ROLES = frozenset(Role)
ADMIN_ONLY = frozenset({Role.ADMIN})

# (method, path) -> who may call it
MATRIX: dict[tuple[str, str], str | frozenset[Role]] = {
    ("GET", "/health"): EVERYONE,
    ("GET", "/ready"): EVERYONE,
    ("GET", "/instruments"): ALL_ROLES,
    ("GET", "/instruments/{instrument_id}"): ALL_ROLES,
    ("POST", "/instruments"): ADMIN_ONLY,
    ("PATCH", "/instruments/{instrument_id}"): ADMIN_ONLY,
    ("POST", "/instruments/{instrument_id}/retire"): ADMIN_ONLY,
    ("GET", "/instruments/{instrument_id}/bars"): ALL_ROLES,
    ("GET", "/instruments/{instrument_id}/candles"): ALL_ROLES,
    ("GET", "/instruments/{instrument_id}/metrics"): ALL_ROLES,
    ("GET", "/instruments/{instrument_id}/returns"): ALL_ROLES,
    ("GET", "/instruments/{instrument_id}/corporate-actions"): ALL_ROLES,
    ("GET", "/instruments/{instrument_id}/gaps"): ALL_ROLES,
    ("GET", "/instruments/{instrument_id}/quote"): ALL_ROLES,
    ("GET", "/data-quality"): frozenset({Role.ADMIN, Role.QUANT, Role.ANALYST}),
}


def test_every_route_has_a_declared_rule() -> None:
    app = build_app(
        make_settings("postgresql+asyncpg://x/y"), revocations=RevocationList(FakeAsyncRedis())
    )
    found = {
        (method.upper(), path.removeprefix(API))
        for path, operations in app.openapi()["paths"].items()
        for method in operations
    }
    assert found == set(MATRIX)


def body_for(method: str, path: str, n: int) -> dict[str, Any] | None:
    if method == "POST" and path == "/instruments":
        return {**NEW_INSTRUMENT, "symbol": f"T{n}"}
    if method == "PATCH":
        return {"notes": "hello"}
    return None


async def test_every_route_allows_exactly_the_declared_roles(client: httpx.AsyncClient) -> None:
    admin = bearer(make_token(Role.ADMIN))
    created = await client.post(f"{API}/instruments", json=NEW_INSTRUMENT, headers=admin)
    assert created.status_code == 201, created.text
    target = created.json()["id"]
    callers: list[tuple[str, dict[str, str]]] = [
        ("anonymous", {}),
        ("forged", bearer(make_token(Role.ADMIN, forged=True))),
    ] + [(role.value, bearer(make_token(role))) for role in Role]
    n = 0
    for (method, path), rule in MATRIX.items():
        url = API + path.replace("{instrument_id}", target)
        for who, headers in callers:
            n += 1
            response = await client.request(
                method, url, headers=headers, json=body_for(method, path, n)
            )
            where = (method, path, who, response.text)
            if rule == EVERYONE:
                assert response.status_code in (200, 503), where
                continue
            assert isinstance(rule, frozenset)
            if who in {role.value for role in rule}:
                assert response.status_code in (200, 201), where
            elif who in ("anonymous", "forged"):
                assert response.status_code == 401, where
            else:
                assert response.status_code == 403, where


async def test_an_admin_can_add_annotate_and_retire_and_a_viewer_sees_it(
    client: httpx.AsyncClient,
) -> None:
    admin, viewer = bearer(make_token(Role.ADMIN)), bearer(make_token(Role.VIEWER))
    created = (await client.post(f"{API}/instruments", json=NEW_INSTRUMENT, headers=admin)).json()
    again = await client.post(f"{API}/instruments", json=NEW_INSTRUMENT, headers=admin)
    assert again.status_code == 409
    assert again.json()["existing_id"] == created["id"]
    patched = await client.patch(
        f"{API}/instruments/{created['id']}", json={"sector": "Software"}, headers=admin
    )
    assert patched.json()["sector"] == "Software"
    await client.post(f"{API}/instruments/{created['id']}/retire", headers=admin)
    listed = await client.get(f"{API}/instruments", params={"status": "retired"}, headers=viewer)
    assert [i["symbol"] for i in listed.json()] == ["ZZTEST"]
    missing = await client.get(f"{API}/instruments/{uuid.uuid4()}", headers=viewer)
    assert missing.status_code == 404


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"symbol": "aapl"}, "symbol"),
        ({"symbol": "A" * 16}, "symbol"),
        ({"symbol": ""}, "symbol"),
        ({"exchange": "NASDAQ"}, "exchange"),
        ({"exchange": "xnas"}, "exchange"),
        ({"currency": "US"}, "currency"),
        ({"currency": "usd"}, "currency"),
        ({"asset_class": "bond"}, "asset_class"),
        ({"sector": ""}, "sector"),
        ({"sector": "S" * 81}, "sector"),
        ({"name": ""}, "name"),
        ({"surprise": 1}, "surprise"),
    ],
)
async def test_a_bad_body_is_a_422_and_never_a_500(
    client: httpx.AsyncClient, overrides: dict[str, Any], field: str
) -> None:
    admin = bearer(make_token(Role.ADMIN))
    response = await client.post(
        f"{API}/instruments", json={**NEW_INSTRUMENT, **overrides}, headers=admin
    )
    assert response.status_code == 422, response.text


async def test_patch_validates_and_refuses_an_empty_or_unknown_change(
    client: httpx.AsyncClient,
) -> None:
    admin = bearer(make_token(Role.ADMIN))
    created = (await client.post(f"{API}/instruments", json=NEW_INSTRUMENT, headers=admin)).json()
    url = f"{API}/instruments/{created['id']}"
    for body in ({}, {"sector": "S" * 81}, {"symbol": "OTHER"}, {"status": "retired"}):
        assert (await client.patch(url, json=body, headers=admin)).status_code == 422
    assert (await client.get(f"{API}/instruments/not-a-uuid", headers=admin)).status_code == 422
