import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from qs_platform.models import users
from qs_template import Database
from qs_template.messaging import outbox
from tests.conftest import ADMIN_PASSWORD, bearer, login

pytestmark = pytest.mark.db

API = "/api/platform"


async def admin_token(client: httpx.AsyncClient) -> str:
    return await login(client, "admin", ADMIN_PASSWORD)


async def create_user(
    client: httpx.AsyncClient, token: str, username: str, role: str = "quant", **extra: Any
) -> dict[str, Any]:
    body = {
        "username": username,
        "email": f"{username}@quantsim.dev",
        "display_name": username.title(),
        "password": f"{username}-password-123",
        "role": role,
        **extra,
    }
    response = await client.post(f"{API}/users", json=body, headers=bearer(token))
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()
    return created


async def events(database: Database) -> list[tuple[str, str]]:
    async with database.transaction() as session:
        rows = await session.execute(
            select(outbox.c.event_type, outbox.c.message_key).order_by(outbox.c.id)
        )
        return [(r[0], r[1]) for r in rows]


# Sign-in --------------------------------------------------------------------------------


async def test_login_returns_a_token_for_the_user(client: httpx.AsyncClient) -> None:
    response = await client.post(
        f"{API}/auth/login", json={"username": "ADMIN", "password": ADMIN_PASSWORD}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "Bearer"
    assert body["expires_in"] == 900
    assert body["user"]["username"] == "admin"
    assert body["user"]["role"] == "admin"
    assert response.headers["Cache-Control"] == "no-store"


async def test_wrong_password_and_unknown_user_look_the_same(client: httpx.AsyncClient) -> None:
    wrong = await client.post(f"{API}/auth/login", json={"username": "admin", "password": "nope"})
    unknown = await client.post(
        f"{API}/auth/login", json={"username": "nobody", "password": "nope"}
    )

    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["detail"] == unknown.json()["detail"]


async def test_repeated_failures_lock_the_account(client: httpx.AsyncClient) -> None:
    for _ in range(3):
        await client.post(f"{API}/auth/login", json={"username": "admin", "password": "nope"})

    locked = await client.post(
        f"{API}/auth/login", json={"username": "admin", "password": ADMIN_PASSWORD}
    )

    assert locked.status_code == 429
    assert locked.json()["retry_after_seconds"] > 0


async def test_a_successful_login_resets_the_failure_count(
    client: httpx.AsyncClient, database: Database
) -> None:
    for _ in range(2):
        await client.post(f"{API}/auth/login", json={"username": "admin", "password": "nope"})
    await admin_token(client)
    await client.post(f"{API}/auth/login", json={"username": "admin", "password": "nope"})

    assert (
        await client.post(
            f"{API}/auth/login", json={"username": "admin", "password": ADMIN_PASSWORD}
        )
    ).status_code == 200


async def test_me_returns_the_signed_in_user(client: httpx.AsyncClient) -> None:
    token = await admin_token(client)

    response = await client.get(f"{API}/auth/me", headers=bearer(token))

    assert response.status_code == 200
    assert response.json()["username"] == "admin"


async def test_key_set_is_public_and_cacheable(client: httpx.AsyncClient) -> None:
    response = await client.get(f"{API}/.well-known/jwks.json")

    assert response.status_code == 200
    assert response.json()["keys"][0]["kid"] == "test-key-1"
    assert "max-age" in response.headers["Cache-Control"]


# User management ------------------------------------------------------------------------


async def test_admin_creates_a_user_who_can_sign_in(
    client: httpx.AsyncClient, database: Database
) -> None:
    token = await admin_token(client)

    user = await create_user(client, token, "sara", role="analyst")
    sara = await login(client, "sara", "sara-password-123")

    me = (await client.get(f"{API}/auth/me", headers=bearer(sara))).json()
    assert me["id"] == user["id"]
    assert me["role"] == "analyst"
    assert ("user.created", user["id"]) in await events(database)


async def test_duplicate_username_or_email_is_a_conflict(client: httpx.AsyncClient) -> None:
    token = await admin_token(client)
    await create_user(client, token, "sara")

    for body in (
        {"username": "SARA".lower(), "email": "other@quantsim.dev"},
        {"username": "sara2", "email": "SARA@quantsim.dev"},
    ):
        response = await client.post(
            f"{API}/users",
            json={**body, "display_name": "x", "password": "long-enough-pass", "role": "viewer"},
            headers=bearer(token),
        )
        assert response.status_code == 409


@pytest.mark.parametrize(
    "body",
    [
        {"username": "No Spaces", "email": "a@quantsim.dev", "password": "long-enough-pass"},
        {"username": "ok", "email": "a@quantsim.dev", "password": "long-enough-pass"},
        {"username": "okay", "email": "not-an-email", "password": "long-enough-pass"},
        {"username": "okay", "email": "a@quantsim.dev", "password": "short"},
        {
            "username": "okay",
            "email": "a@quantsim.dev",
            "password": "long-enough-pass",
            "role": "superuser",
        },
    ],
)
async def test_invalid_users_are_rejected(client: httpx.AsyncClient, body: dict[str, str]) -> None:
    token = await admin_token(client)
    payload = {"display_name": "x", "role": "viewer", **body}

    response = await client.post(f"{API}/users", json=payload, headers=bearer(token))

    assert response.status_code == 422


@pytest.mark.parametrize("role", ["quant", "analyst", "viewer"])
async def test_only_admins_manage_users(client: httpx.AsyncClient, role: str) -> None:
    token = await admin_token(client)
    await create_user(client, token, "member", role=role)
    member = await login(client, "member", "member-password-123")

    listing = await client.get(f"{API}/users", headers=bearer(member))
    creating = await client.post(f"{API}/users", json={}, headers=bearer(member))

    assert listing.status_code == 403
    assert creating.status_code == 403


async def test_requests_without_a_token_are_refused(client: httpx.AsyncClient) -> None:
    assert (await client.get(f"{API}/users")).status_code == 401
    assert (await client.get(f"{API}/auth/me")).status_code == 401


async def test_listing_hides_deactivated_users_by_default(client: httpx.AsyncClient) -> None:
    token = await admin_token(client)
    sara = await create_user(client, token, "sara")
    await create_user(client, token, "bilal")
    await client.post(f"{API}/users/{sara['id']}/deactivate", headers=bearer(token))

    active = (await client.get(f"{API}/users", headers=bearer(token))).json()
    everyone = (
        await client.get(f"{API}/users?include_inactive=true", headers=bearer(token))
    ).json()

    assert [u["username"] for u in active["items"]] == ["admin", "bilal"]
    assert everyone["total"] == 3


async def test_unknown_users_are_not_found(client: httpx.AsyncClient) -> None:
    token = await admin_token(client)

    response = await client.get(f"{API}/users/{uuid.uuid4()}", headers=bearer(token))

    assert response.status_code == 404


# Deactivation, role changes and revocation ---------------------------------------------


async def test_deactivation_cuts_off_existing_tokens_and_blocks_sign_in(
    client: httpx.AsyncClient, database: Database
) -> None:
    token = await admin_token(client)
    sara = await create_user(client, token, "sara")
    sara_token = await login(client, "sara", "sara-password-123")

    response = await client.post(f"{API}/users/{sara['id']}/deactivate", headers=bearer(token))

    assert response.status_code == 200
    assert response.json()["is_active"] is False
    assert (await client.get(f"{API}/auth/me", headers=bearer(sara_token))).status_code == 401
    denied = await client.post(
        f"{API}/auth/login", json={"username": "sara", "password": "sara-password-123"}
    )
    assert denied.status_code == 401
    assert ("user.deactivated", sara["id"]) in await events(database)


async def test_reactivation_restores_access(client: httpx.AsyncClient) -> None:
    token = await admin_token(client)
    sara = await create_user(client, token, "sara")
    await client.post(f"{API}/users/{sara['id']}/deactivate", headers=bearer(token))

    response = await client.post(f"{API}/users/{sara['id']}/reactivate", headers=bearer(token))

    assert response.json()["is_active"] is True
    assert await login(client, "sara", "sara-password-123")


async def test_role_change_applies_at_once(client: httpx.AsyncClient, database: Database) -> None:
    token = await admin_token(client)
    sara = await create_user(client, token, "sara", role="viewer")
    old_token = await login(client, "sara", "sara-password-123")

    response = await client.put(
        f"{API}/users/{sara['id']}/role", json={"role": "quant"}, headers=bearer(token)
    )

    assert response.json()["role"] == "quant"
    assert (await client.get(f"{API}/auth/me", headers=bearer(old_token))).status_code == 401
    new_token = await login(client, "sara", "sara-password-123")
    assert (await client.get(f"{API}/auth/me", headers=bearer(new_token))).json()["role"] == "quant"
    assert ("user.role_changed", sara["id"]) in await events(database)


async def test_the_last_admin_cannot_be_removed(client: httpx.AsyncClient) -> None:
    token = await admin_token(client)
    me = (await client.get(f"{API}/auth/me", headers=bearer(token))).json()

    deactivate = await client.post(f"{API}/users/{me['id']}/deactivate", headers=bearer(token))
    demote = await client.put(
        f"{API}/users/{me['id']}/role", json={"role": "viewer"}, headers=bearer(token)
    )

    assert deactivate.status_code == demote.status_code == 409


async def test_an_admin_can_be_removed_while_another_remains(client: httpx.AsyncClient) -> None:
    token = await admin_token(client)
    second = await create_user(client, token, "second.admin", role="admin")

    response = await client.post(f"{API}/users/{second['id']}/deactivate", headers=bearer(token))

    assert response.status_code == 200


# Audit trail ----------------------------------------------------------------------------


async def test_history_shows_who_changed_what_without_secrets(
    client: httpx.AsyncClient, database: Database
) -> None:
    token = await admin_token(client)
    admin_id = (await client.get(f"{API}/auth/me", headers=bearer(token))).json()["id"]
    sara = await create_user(client, token, "sara", role="viewer")
    await client.put(
        f"{API}/users/{sara['id']}/role", json={"role": "analyst"}, headers=bearer(token)
    )
    await client.post(f"{API}/users/{sara['id']}/deactivate", headers=bearer(token))

    history = (await client.get(f"{API}/users/{sara['id']}/history", headers=bearer(token))).json()

    assert [h["operation"] for h in history] == ["INSERT", "UPDATE", "UPDATE"]
    assert {h["changed_by"] for h in history} == {admin_id}
    assert history[1]["changes"]["role"] == {"from": "viewer", "to": "analyst"}
    assert history[2]["changes"]["is_active"] == {"from": True, "to": False}
    async with database.transaction() as session:
        raw = (await session.execute(text("SELECT old_data, new_data FROM audit_log"))).all()
    assert "argon2" not in str(raw)


# Database rules -------------------------------------------------------------------------


async def test_the_database_itself_rejects_unknown_roles(database: Database) -> None:
    with pytest.raises(IntegrityError, match="users_role_valid"):
        async with database.transaction() as session:
            await session.execute(
                users.insert().values(
                    username="rogue",
                    email="rogue@quantsim.dev",
                    display_name="Rogue",
                    password_hash="x",
                    role="superuser",
                )
            )
