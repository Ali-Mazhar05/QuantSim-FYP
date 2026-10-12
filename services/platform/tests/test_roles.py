"""Promoting and demoting users end to end (spec: role-administration)."""

import asyncio

import httpx
import pytest
from sqlalchemy import select

from qs_template import Database
from qs_template.auth import ROLE_CAPABILITIES, Role
from qs_template.messaging import outbox
from tests.conftest import ADMIN_PASSWORD, bearer, invite_and_accept, login

pytestmark = pytest.mark.db

API = "/api/platform"


async def capabilities(client: httpx.AsyncClient, username: str) -> list[str]:
    token = await login(client, username, f"{username}-password-123")
    me = (await client.get(f"{API}/auth/me", headers=bearer(token))).json()
    result: list[str] = me["capabilities"]
    return result


async def test_promote_to_admin_and_back_with_capabilities_after_each_sign_in(
    client: httpx.AsyncClient,
) -> None:
    admin = await login(client, "admin", ADMIN_PASSWORD)
    omar = await invite_and_accept(client, admin, "omar", "viewer")

    for role in (Role.QUANT, Role.ADMIN, Role.VIEWER):
        changed = await client.put(
            f"{API}/users/{omar['id']}/role", json={"role": role.value}, headers=bearer(admin)
        )
        assert changed.status_code == 200
        assert await capabilities(client, "omar") == sorted(
            c.value for c in ROLE_CAPABILITIES[role]
        )


async def test_a_demoted_users_old_tokens_are_refused(client: httpx.AsyncClient) -> None:
    admin = await login(client, "admin", ADMIN_PASSWORD)
    omar = await invite_and_accept(client, admin, "omar", "quant")
    session = (
        await client.post(
            f"{API}/auth/login", json={"username": "omar", "password": "omar-password-123"}
        )
    ).json()

    await client.put(
        f"{API}/users/{omar['id']}/role", json={"role": "viewer"}, headers=bearer(admin)
    )

    me = await client.get(f"{API}/auth/me", headers=bearer(session["access_token"]))
    refreshed = await client.post(
        f"{API}/auth/refresh", json={"refresh_token": session["refresh_token"]}
    )
    assert me.status_code == refreshed.status_code == 401


async def test_setting_the_same_role_again_publishes_nothing(
    client: httpx.AsyncClient, database: Database
) -> None:
    admin = await login(client, "admin", ADMIN_PASSWORD)
    omar = await invite_and_accept(client, admin, "omar", "quant")

    async def count() -> int:
        async with database.transaction() as session:
            return len((await session.execute(select(outbox.c.id))).all())

    before = await count()
    same = await client.put(
        f"{API}/users/{omar['id']}/role", json={"role": "quant"}, headers=bearer(admin)
    )

    assert same.status_code == 200
    assert await count() == before


async def test_two_admins_demoting_each_other_at_once_leave_one_admin(
    client: httpx.AsyncClient,
) -> None:
    admin = await login(client, "admin", ADMIN_PASSWORD)
    second = await invite_and_accept(client, admin, "second.admin", "admin")
    other = await login(client, "second.admin", "second.admin-password-123")
    admin_id = (await client.get(f"{API}/auth/me", headers=bearer(admin))).json()["id"]

    results = await asyncio.gather(
        client.put(
            f"{API}/users/{second['id']}/role", json={"role": "quant"}, headers=bearer(admin)
        ),
        client.put(f"{API}/users/{admin_id}/role", json={"role": "quant"}, headers=bearer(other)),
    )

    assert sorted(r.status_code for r in results) in ([200, 409], [200, 401])
    survivors = []
    for name, password in (
        ("admin", ADMIN_PASSWORD),
        ("second.admin", "second.admin-password-123"),
    ):
        token = await login(client, name, password)
        me = (await client.get(f"{API}/auth/me", headers=bearer(token))).json()
        survivors.append(me["role"])
    assert survivors.count("admin") == 1
