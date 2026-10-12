"""Forgot and reset password, admin invitations, stale sign-up clean-up and the test
accounts (spec: account-email)."""

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fakeredis import FakeAsyncRedis
from sqlalchemy import select, text, update

from qs_platform.accounts import AccountService
from qs_platform.keys import SigningKeys
from qs_platform.limits import RateLimiter
from qs_platform.models import account_tokens, users
from qs_platform.service import UserService
from qs_template import Database
from qs_template.revocation import RevocationList
from tests.conftest import (
    ADMIN_PASSWORD,
    SIGNING_KEY,
    bearer,
    invite_and_accept,
    last_link,
    link_token,
    login,
    mails_to,
    make_settings,
)

pytestmark = pytest.mark.db

API = "/api/platform"


async def try_login(client: httpx.AsyncClient, username: str, password: str) -> httpx.Response:
    return await client.post(f"{API}/auth/login", json={"username": username, "password": password})


async def forgot(client: httpx.AsyncClient, email: str) -> httpx.Response:
    return await client.post(f"{API}/auth/forgot-password", json={"email": email})


async def reset(client: httpx.AsyncClient, link: str, password: str) -> httpx.Response:
    return await client.post(
        f"{API}/auth/reset-password", json={"token": link_token(link), "password": password}
    )


def accounts_service(redis: FakeAsyncRedis) -> AccountService:
    settings = make_settings()
    keys = SigningKeys(settings.signing_key_pem, settings.signing_key_id, None)
    assert SIGNING_KEY
    users_service = UserService(settings, keys, RevocationList(redis))
    return AccountService(settings, users_service, RateLimiter(redis))


# Forgot and reset password ------------------------------------------------------------


async def test_forgot_password_answers_the_same_for_known_and_unknown_emails(
    client: httpx.AsyncClient, database: Database
) -> None:
    known = await forgot(client, "admin@quantsim.dev")
    unknown = await forgot(client, "nobody@example.com")

    assert known.status_code == unknown.status_code == 202
    assert known.text == unknown.text
    mails = await mails_to(database, "admin@quantsim.dev")
    assert [t for t, _ in mails] == ["reset_password"]
    assert "/set-password#token=" in mails[0][1]["link"]
    assert mails[0][1]["link"].endswith("&purpose=reset")
    assert await mails_to(database, "nobody@example.com") == []


async def test_a_reset_changes_the_password_and_ends_every_session(
    client: httpx.AsyncClient,
) -> None:
    first = (await try_login(client, "admin", ADMIN_PASSWORD)).json()
    second = (await try_login(client, "admin", ADMIN_PASSWORD)).json()
    await forgot(client, "admin@quantsim.dev")
    link = await last_link(client, "admin@quantsim.dev", "reset_password")

    response = await reset(client, link, "brand-new-password-1")

    assert response.json() == {"status": "password_set"}
    for session in (first, second):
        refreshed = await client.post(
            f"{API}/auth/refresh", json={"refresh_token": session["refresh_token"]}
        )
        assert refreshed.status_code == 401
        me = await client.get(f"{API}/auth/me", headers=bearer(session["access_token"]))
        assert me.status_code == 401
    assert (await try_login(client, "admin", ADMIN_PASSWORD)).status_code == 401
    assert (await try_login(client, "admin", "brand-new-password-1")).status_code == 200


async def test_a_reset_unlocks_a_locked_account(client: httpx.AsyncClient) -> None:
    for n in range(3):
        await try_login(client, "admin", f"wrong-password-{n}")
    assert (await try_login(client, "admin", ADMIN_PASSWORD)).status_code == 429

    await forgot(client, "admin@quantsim.dev")
    await reset(
        client,
        await last_link(client, "admin@quantsim.dev", "reset_password"),
        "brand-new-password-1",
    )

    assert (await try_login(client, "admin", "brand-new-password-1")).status_code == 200


async def test_an_expired_reset_link_is_refused(
    client: httpx.AsyncClient, database: Database
) -> None:
    await forgot(client, "admin@quantsim.dev")
    link = await last_link(client, "admin@quantsim.dev", "reset_password")
    async with database.transaction() as session:
        past = datetime.now(UTC) - timedelta(minutes=61)
        await session.execute(
            update(account_tokens).values(created_at=past - timedelta(hours=1), expires_at=past)
        )

    response = await reset(client, link, "brand-new-password-1")

    assert response.status_code == 400
    assert (await try_login(client, "admin", ADMIN_PASSWORD)).status_code == 200


async def test_a_short_password_is_refused_and_the_link_stays_usable(
    client: httpx.AsyncClient,
) -> None:
    await forgot(client, "admin@quantsim.dev")
    link = await last_link(client, "admin@quantsim.dev", "reset_password")

    short = await reset(client, link, "short-11chr")
    good = await reset(client, link, "brand-new-password-1")

    assert short.status_code == 422
    assert good.status_code == 200


async def test_reset_emails_link_to_the_environments_site(
    client: httpx.AsyncClient, database: Database
) -> None:
    await forgot(client, "admin@quantsim.dev")

    _, params = (await mails_to(database, "admin@quantsim.dev"))[0]
    assert params["link"].startswith("http://localhost:5173/set-password#token=")


# Invitations --------------------------------------------------------------------------


async def test_an_invited_user_cannot_sign_in_until_they_set_a_password(
    client: httpx.AsyncClient, database: Database
) -> None:
    admin = await login(client, "admin", ADMIN_PASSWORD)
    created = await client.post(
        f"{API}/users",
        json={
            "username": "omar",
            "email": "omar@example.com",
            "display_name": "Omar",
            "role": "analyst",
        },
        headers=bearer(admin),
    )

    assert created.status_code == 201
    assert created.json()["status"] == "invited"
    for guess in ("", "omar-password-123", "anything-at-all-1"):
        assert (await try_login(client, "omar", guess or "x")).status_code == 401
    link = await last_link(client, "omar@example.com", "invite")
    assert link.endswith("&purpose=invite")

    await reset(client, link, "omar-password-123")

    token = await login(client, "omar", "omar-password-123")
    me = (await client.get(f"{API}/auth/me", headers=bearer(token))).json()
    assert me["role"] == "analyst"
    assert me["status"] == "active"


async def test_resending_an_invite_voids_the_old_link(client: httpx.AsyncClient) -> None:
    admin = await login(client, "admin", ADMIN_PASSWORD)
    created = (
        await client.post(
            f"{API}/users",
            json={
                "username": "omar",
                "email": "omar@example.com",
                "display_name": "Omar",
                "role": "viewer",
            },
            headers=bearer(admin),
        )
    ).json()
    old = await last_link(client, "omar@example.com", "invite")

    resent = await client.post(f"{API}/users/{created['id']}/resend-invite", headers=bearer(admin))

    assert resent.status_code == 202
    new = await last_link(client, "omar@example.com", "invite")
    assert (await reset(client, old, "omar-password-123")).status_code == 400
    assert (await reset(client, new, "omar-password-123")).status_code == 200
    again = await client.post(f"{API}/users/{created['id']}/resend-invite", headers=bearer(admin))
    assert again.status_code == 409


async def test_inviting_a_taken_email_tells_the_admin(client: httpx.AsyncClient) -> None:
    admin = await login(client, "admin", ADMIN_PASSWORD)

    response = await client.post(
        f"{API}/users",
        json={
            "username": "someone",
            "email": "ADMIN@quantsim.dev",
            "display_name": "Someone",
            "role": "viewer",
        },
        headers=bearer(admin),
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "That username or email is already in use."


async def test_an_admin_can_invite_another_admin(client: httpx.AsyncClient) -> None:
    admin = await login(client, "admin", ADMIN_PASSWORD)

    await invite_and_accept(client, admin, "second.admin", "admin")

    token = await login(client, "second.admin", "second.admin-password-123")
    me = (await client.get(f"{API}/auth/me", headers=bearer(token))).json()
    assert "manage_roles" in me["capabilities"]


# Clean-up and test accounts -----------------------------------------------------------


async def test_stale_sign_ups_are_removed_but_invitations_are_kept(
    client: httpx.AsyncClient, database: Database, redis: FakeAsyncRedis
) -> None:
    admin = await login(client, "admin", ADMIN_PASSWORD)
    await client.post(
        f"{API}/auth/signup",
        json={
            "username": "sara.k",
            "email": "sara@example.com",
            "password": "sara-password-123",
            "account_type": "viewer",
        },
    )
    await client.post(
        f"{API}/users",
        json={
            "username": "omar",
            "email": "omar@example.com",
            "display_name": "Omar",
            "role": "viewer",
        },
        headers=bearer(admin),
    )
    async with database.transaction() as session:
        await session.execute(
            update(users)
            .where(users.c.username.in_(["sara.k", "omar"]))
            .values(created_at=datetime.now(UTC) - timedelta(days=30))
        )

    async with database.transaction() as session:
        removed = await accounts_service(redis).remove_stale_sign_ups(session)

    assert removed == 1
    async with database.transaction() as session:
        names = (await session.execute(select(users.c.username))).scalars().all()
        deleted = (
            await session.execute(text("SELECT count(*) FROM audit_log WHERE operation = 'DELETE'"))
        ).scalar_one()
    assert set(names) == {"admin", "omar"}
    assert deleted == 1
    again = await client.post(
        f"{API}/auth/signup",
        json={
            "username": "sara.k",
            "email": "sara2@example.com",
            "password": "sara-password-123",
            "account_type": "viewer",
        },
    )
    assert again.status_code == 202


async def test_test_accounts_are_seeded_verified_and_can_be_reset(
    client: httpx.AsyncClient, database: Database, redis: FakeAsyncRedis
) -> None:
    service = accounts_service(redis)
    async with database.transaction() as session:
        await service.seed_test_users(session, "test-users-pass-1", "alimazhar@gmail.com")
    async with database.transaction() as session:
        await service.seed_test_users(session, "test-users-pass-2", "alimazhar@gmail.com")

    for name, role in (
        ("test.admin", "admin"),
        ("test.quant", "quant"),
        ("test.analyst", "analyst"),
        ("test.viewer", "viewer"),
    ):
        token = await login(client, name, "test-users-pass-2")
        me = (await client.get(f"{API}/auth/me", headers=bearer(token))).json()
        assert me["role"] == role
        assert me["email"] == f"alimazhar+qs-{role}@gmail.com"
        assert me["status"] == "active"
