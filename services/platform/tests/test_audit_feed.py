"""The platform audit feed: every account change, in the Audit Log page's row shape."""

import httpx
import pytest
from sqlalchemy import text

from qs_template import Database
from tests.conftest import ADMIN_PASSWORD, bearer, invite_and_accept, login

pytestmark = pytest.mark.db

API = "/api/platform"


async def test_feed_lists_account_changes_newest_first_with_actor_and_severity(
    client: httpx.AsyncClient,
) -> None:
    admin = await login(client, "admin", ADMIN_PASSWORD)
    created = await invite_and_accept(client, admin, "ana", "analyst")
    await login(client, "ana", "ana-password-123")
    wrong = await client.post(
        f"{API}/auth/login", json={"username": "ana", "password": "not-her-password"}
    )
    assert wrong.status_code == 401
    changed = await client.put(
        f"{API}/users/{created['id']}/role", json={"role": "quant"}, headers=bearer(admin)
    )
    assert changed.status_code == 200, changed.text
    gone = await client.post(f"{API}/users/{created['id']}/deactivate", headers=bearer(admin))
    assert gone.status_code == 200, gone.text

    response = await client.get(f"{API}/audit", headers=bearer(admin))
    assert response.status_code == 200, response.text
    feed = response.json()

    times = [event["occurred_at"] for event in feed]
    assert times == sorted(times, reverse=True)
    assert len({event["id"] for event in feed}) == len(feed)
    assert {event["service"] for event in feed} == {"Platform"}

    by_action = {event["action"]: event for event in feed}
    invited = by_action["User ana invited"]
    assert invited["actor"] == "admin"
    assert invited["severity"] == "info"
    assert "Analyst" in invited["detail"]
    signed_in = by_action["User ana signed in"]
    assert signed_in["actor"] == "ana"
    assert signed_in["actor_id"] == created["id"]  # her own account, not "the system"
    assert by_action["Failed sign-in for ana"]["severity"] == "warning"
    role = by_action["Role of ana changed"]
    assert role["severity"] == "warning"
    assert "Analyst → Quant" in role["detail"]
    assert role["actor"] == "admin"
    assert by_action["User ana deactivated"]["severity"] == "warning"
    assert feed[0]["action"] == "User ana deactivated"
    assert "argon2" not in response.text
    assert "password_hash" not in response.text


async def test_feed_honours_the_limit(client: httpx.AsyncClient) -> None:
    admin = await login(client, "admin", ADMIN_PASSWORD)
    for name in ("one", "two", "three"):
        await invite_and_accept(client, admin, name, "viewer")
    feed = (await client.get(f"{API}/audit?limit=2", headers=bearer(admin))).json()
    assert len(feed) == 2
    too_many = await client.get(f"{API}/audit?limit=501", headers=bearer(admin))
    assert too_many.status_code == 422


async def test_changes_with_no_acting_user_are_the_system_unless_self_service(
    client: httpx.AsyncClient, database: Database
) -> None:
    admin = await login(client, "admin", ADMIN_PASSWORD)
    created = await invite_and_accept(client, admin, "cli", "viewer")
    await login(client, "cli", "cli-password-123")
    # As a command-line job does it: no audit context, so no acting user is recorded
    async with database.transaction() as session:
        await session.execute(text("UPDATE users SET role = 'analyst' WHERE username = 'cli'"))

    feed = (await client.get(f"{API}/audit", headers=bearer(admin))).json()
    by_action = {event["action"]: event for event in feed}
    system_change = by_action["Role of cli changed"]
    assert system_change["actor_id"] is None
    assert system_change["actor"] is None
    own_sign_in = by_action["User cli signed in"]
    assert own_sign_in["actor_id"] == created["id"]
    assert own_sign_in["actor"] == "cli"


async def test_accounts_created_by_a_command_are_the_system_not_a_sign_up(
    client: httpx.AsyncClient, database: Database
) -> None:
    admin = await login(client, "admin", ADMIN_PASSWORD)
    # As bootstrap-admin and seed-test-users do it: verified at birth, no acting user
    async with database.transaction() as session:
        await session.execute(
            text(
                "INSERT INTO users (username, email, display_name, role, email_verified_at,"
                " approved_at) VALUES ('seeded', 'seeded@quantsim.dev', 'Seeded', 'viewer',"
                " now(), now())"
            )
        )
    signed_up = await client.post(
        f"{API}/auth/signup",
        json={
            "username": "newcomer",
            "email": "newcomer@quantsim.dev",
            "password": "newcomer-password-123",
            "account_type": "viewer",
        },
    )
    assert signed_up.status_code in (200, 201, 202), signed_up.text

    feed = (await client.get(f"{API}/audit", headers=bearer(admin))).json()
    by_action = {event["action"]: event for event in feed}
    seeded = by_action["Account seeded created"]
    assert seeded["actor_id"] is None
    assert "User seeded signed up" not in by_action
    newcomer = by_action["User newcomer signed up"]
    assert newcomer["actor"] == "newcomer"
