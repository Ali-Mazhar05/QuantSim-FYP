"""Authorization of every Platform route, for every role (FR-16, SPEC section 1).

The matrix below is the contract. A route missing from it fails the test, so a new
endpoint cannot ship without a declared rule.
"""

from typing import Any

import httpx
import pytest
from fakeredis import FakeAsyncRedis

from qs_platform.limits import RateLimiter
from qs_platform.main import build_app
from qs_template import Database
from qs_template.auth import ROLE_CAPABILITIES, Role
from qs_template.revocation import RevocationList
from tests.conftest import (
    ADMIN_PASSWORD,
    bearer,
    invite_and_accept,
    last_link,
    link_token,
    login,
    make_settings,
)

pytestmark = pytest.mark.db

API = "/api/platform"
EVERYONE = "everyone"  # no token needed
SIGNED_IN = "signed-in"  # any role
ALL_ROLES = frozenset(Role)

# (method, path) -> who may call it
MATRIX: dict[tuple[str, str], str | frozenset[Role]] = {
    ("POST", "/auth/login"): EVERYONE,
    ("POST", "/auth/refresh"): EVERYONE,
    ("POST", "/auth/logout"): EVERYONE,
    ("POST", "/auth/signup"): EVERYONE,
    ("POST", "/auth/verify-email"): EVERYONE,
    ("POST", "/auth/resend-verification"): EVERYONE,
    ("POST", "/auth/forgot-password"): EVERYONE,
    ("POST", "/auth/reset-password"): EVERYONE,
    ("GET", "/.well-known/jwks.json"): EVERYONE,
    ("GET", "/health"): EVERYONE,
    ("GET", "/ready"): EVERYONE,
    ("GET", "/auth/me"): SIGNED_IN,
    ("GET", "/users"): frozenset({Role.ADMIN}),
    ("POST", "/users"): frozenset({Role.ADMIN}),
    ("GET", "/users/{user_id}"): frozenset({Role.ADMIN}),
    ("POST", "/users/{user_id}/deactivate"): frozenset({Role.ADMIN}),
    ("POST", "/users/{user_id}/reactivate"): frozenset({Role.ADMIN}),
    ("POST", "/users/{user_id}/approve"): frozenset({Role.ADMIN}),
    ("POST", "/users/{user_id}/reject"): frozenset({Role.ADMIN}),
    ("POST", "/users/{user_id}/resend-invite"): frozenset({Role.ADMIN}),
    ("PUT", "/users/{user_id}/role"): frozenset({Role.ADMIN}),
    ("GET", "/users/{user_id}/history"): frozenset({Role.ADMIN}),
}


def platform_routes() -> set[tuple[str, str]]:
    """Every API route, from the app's own OpenAPI document (it lists every operation)."""
    redis = FakeAsyncRedis()
    app = build_app(make_settings(), revocations=RevocationList(redis), limiter=RateLimiter(redis))
    found = set()
    for path, operations in app.openapi()["paths"].items():
        for method in operations:
            found.add((method.upper(), path.removeprefix(API)))
    return found


def test_every_route_has_a_declared_rule() -> None:
    assert platform_routes() == set(MATRIX)


def body_for(method: str, path: str, username: str) -> dict[str, Any] | None:
    if path == "/users" and method == "POST":
        return {
            "username": f"new.{username}",
            "email": f"new.{username}@quantsim.dev",
            "display_name": "New",
            "role": "viewer",
        }
    if path.endswith("/role"):
        return {"role": "analyst"}
    if path == "/auth/login":
        return {"username": "nobody", "password": "x"}
    if path in ("/auth/refresh", "/auth/logout"):
        return {"refresh_token": "x" * 43}
    if path == "/auth/signup":
        return {
            "username": f"signup.{username}",
            "email": f"signup.{username}@quantsim.dev",
            "password": "a-long-password-123",
            "account_type": "viewer",
        }
    if path in ("/auth/resend-verification", "/auth/forgot-password"):
        return {"email": "nobody@quantsim.dev"}
    if path == "/auth/verify-email":
        return {"token": "x" * 43}
    if path == "/auth/reset-password":
        return {"token": "x" * 43, "password": "a-long-password-123"}
    return None


@pytest.fixture
async def tokens(client: httpx.AsyncClient) -> dict[Role, str]:
    admin = await login(client, "admin", ADMIN_PASSWORD)
    result = {Role.ADMIN: admin}
    for role in (Role.QUANT, Role.ANALYST, Role.VIEWER):
        name = f"{role.value}.user"
        await invite_and_accept(client, admin, name, role.value)
        result[role] = await login(client, name, f"{name}-password-123")
    return result


async def test_every_route_allows_exactly_the_declared_roles(
    client: httpx.AsyncClient, tokens: dict[Role, str], database: Database
) -> None:
    target = (
        await client.post(
            f"{API}/users",
            json={
                "username": "target",
                "email": "target@quantsim.dev",
                "display_name": "Target",
                "password": "target-password-123",
                "role": "viewer",
            },
            headers=bearer(tokens[Role.ADMIN]),
        )
    ).json()
    callers: list[tuple[str, dict[str, str]]] = [("anonymous", {})] + [
        (role.value, bearer(token)) for role, token in tokens.items()
    ]
    for (method, path), rule in MATRIX.items():
        url = API + path.replace("{user_id}", target["id"])
        for who, headers in callers:
            response = await client.request(
                method, url, headers=headers, json=body_for(method, path, who)
            )
            if rule == EVERYONE:
                # Public routes may still say 401 (a wrong password); never 403
                assert response.status_code != 403, (method, path, who, response.text)
                continue
            if who == "anonymous":
                allowed = False
            else:
                roles = ALL_ROLES if rule == SIGNED_IN else rule
                allowed = Role(who) in roles
            if allowed:
                assert response.status_code not in (401, 403), (method, path, who, response.text)
            else:
                expected = 401 if who == "anonymous" else 403
                assert response.status_code == expected, (method, path, who, response.text)


async def test_me_returns_the_role_and_its_capabilities(
    client: httpx.AsyncClient, tokens: dict[Role, str]
) -> None:
    for role, token in tokens.items():
        me = (await client.get(f"{API}/auth/me", headers=bearer(token))).json()
        assert me["role"] == role.value
        assert set(me["capabilities"]) == {c.value for c in ROLE_CAPABILITIES[role]}
    viewer = (await client.get(f"{API}/auth/me", headers=bearer(tokens[Role.VIEWER]))).json()
    admin = (await client.get(f"{API}/auth/me", headers=bearer(tokens[Role.ADMIN]))).json()
    assert viewer["role_rank"] < admin["role_rank"]
    assert "manage_users" not in viewer["capabilities"]
    assert "manage_users" in admin["capabilities"]


async def test_user_status_is_shown_as_the_users_page_expects(
    client: httpx.AsyncClient, tokens: dict[Role, str]
) -> None:
    admin = tokens[Role.ADMIN]
    created = await client.post(
        f"{API}/users",
        json={
            "username": "fresh",
            "email": "fresh@quantsim.dev",
            "display_name": "Fresh",
            "role": "viewer",
        },
        headers=bearer(admin),
    )
    fresh = created.json()
    assert fresh["status"] == "invited"

    link = await last_link(client, "fresh@quantsim.dev", "invite")
    await client.post(
        f"{API}/auth/reset-password",
        json={"token": link_token(link), "password": "fresh-password-123"},
    )
    accepted = await client.get(f"{API}/users/{fresh['id']}", headers=bearer(admin))
    assert accepted.json()["status"] == "active"

    await client.post(f"{API}/users/{fresh['id']}/deactivate", headers=bearer(admin))
    disabled = await client.get(f"{API}/users/{fresh['id']}", headers=bearer(admin))
    assert disabled.json()["status"] == "disabled"
