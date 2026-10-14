"""Self sign-up, email verification, admin approval and sign-in by email
(specs: account-access, account-email, role-administration)."""

from typing import Any

import httpx
import pytest
from fakeredis import FakeAsyncRedis
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import select, text

from qs_platform.limits import RateLimiter
from qs_platform.main import build_app
from qs_platform.models import users
from qs_template import Database
from qs_template.auth import ROLE_CAPABILITIES, Role
from qs_template.messaging import outbox
from qs_template.revocation import RevocationList
from tests.conftest import (
    ADMIN_PASSWORD,
    PlatformClient,
    bearer,
    last_link,
    link_token,
    login,
    mails_to,
    make_settings,
)

pytestmark = pytest.mark.db

API = "/api/platform"
PASSWORD = "sara-password-123"


def signup_body(
    username: str = "sara.k", email: str = "sara@example.com", account_type: str = "quant"
) -> dict[str, str]:
    return {
        "username": username,
        "email": email,
        "password": PASSWORD,
        "account_type": account_type,
    }


async def sign_up(client: httpx.AsyncClient, **kwargs: str) -> httpx.Response:
    return await client.post(f"{API}/auth/signup", json=signup_body(**kwargs))


async def verify(client: httpx.AsyncClient, email: str) -> httpx.Response:
    link = await last_link(client, email, "verify_email")
    return await client.post(f"{API}/auth/verify-email", json={"token": link_token(link)})


async def try_login(client: httpx.AsyncClient, username: str, password: str) -> httpx.Response:
    return await client.post(f"{API}/auth/login", json={"username": username, "password": password})


async def user_row(database: Database, username: str) -> Any:
    async with database.transaction() as session:
        return (await session.execute(select(users).where(users.c.username == username))).one()


async def event_types(database: Database) -> list[str]:
    async with database.transaction() as session:
        rows = await session.execute(select(outbox.c.event_type).order_by(outbox.c.id))
        return [r[0] for r in rows]


# Sign-up ------------------------------------------------------------------------------


async def test_sign_up_creates_an_unverified_account_and_emails_a_link(
    client: httpx.AsyncClient, database: Database
) -> None:
    response = await sign_up(client)

    assert response.status_code == 202
    assert response.json() == {"message": "Check your email to finish creating your account."}
    assert "access_token" not in response.text
    row = await user_row(database, "sara.k")
    assert row.role == "quant"
    assert row.email_verified_at is None
    assert row.approved_at is None
    assert row.display_name == "sara.k"
    assert row.created_by == row.id
    mails = await mails_to(database, "sara@example.com")
    assert [t for t, _ in mails] == ["verify_email"]
    assert mails[0][1]["link"].startswith("http://localhost:5173/verify-email#token=")
    assert "user.created" in await event_types(database)


async def test_the_password_is_stored_only_as_an_argon2_hash(
    client: httpx.AsyncClient, database: Database
) -> None:
    await sign_up(client)

    row = await user_row(database, "sara.k")
    assert row.password_hash.startswith("$argon2id$")
    async with database.transaction() as session:
        dumped = str((await session.execute(text("SELECT * FROM mail_outbox"))).all())
        dumped += str((await session.execute(text("SELECT * FROM outbox"))).all())
        dumped += str((await session.execute(text("SELECT * FROM audit_log"))).all())
    assert PASSWORD not in dumped
    assert "argon2" not in dumped


async def test_admin_cannot_be_chosen_at_sign_up(
    client: httpx.AsyncClient, database: Database
) -> None:
    response = await sign_up(client, account_type="admin")

    assert response.status_code == 422
    assert await mails_to(database, "sara@example.com") == []


@pytest.mark.parametrize(
    "change",
    [
        {"username": "sk"},
        {"username": "sara k"},
        {"email": "not-an-email"},
        {"password": "short-11chr"},
        {"account_type": None},
    ],
)
async def test_invalid_fields_are_refused(
    client: httpx.AsyncClient, database: Database, change: dict[str, Any]
) -> None:
    body: dict[str, Any] = {**signup_body(), **change}
    body = {k: v for k, v in body.items() if v is not None}

    response = await client.post(f"{API}/auth/signup", json=body)

    assert response.status_code == 422
    async with database.transaction() as session:
        count = (await session.execute(text("SELECT count(*) FROM users"))).scalar_one()
    assert count == 1  # only the bootstrap admin


async def test_a_taken_username_is_reported_in_any_case(client: httpx.AsyncClient) -> None:
    await sign_up(client)

    response = await sign_up(client, username="SARA.K", email="other@example.com")

    assert response.status_code == 409
    assert response.json()["detail"] == "That username is already taken."


async def test_a_verified_email_gets_the_same_answer_and_an_already_have_an_account_mail(
    client: httpx.AsyncClient, database: Database
) -> None:
    await sign_up(client, account_type="viewer")
    await verify(client, "sara@example.com")

    again = await sign_up(client, username="newname", email="Sara@Example.com")

    assert again.status_code == 202
    assert again.json() == {"message": "Check your email to finish creating your account."}
    async with database.transaction() as session:
        count = (await session.execute(text("SELECT count(*) FROM users"))).scalar_one()
    assert count == 2
    templates = [t for t, _ in await mails_to(database, "sara@example.com")]
    assert templates == ["verify_email", "account_exists"]


async def test_an_unverified_email_gets_a_fresh_link_and_no_second_account(
    client: httpx.AsyncClient, database: Database
) -> None:
    await sign_up(client)
    first = await last_link(client, "sara@example.com", "verify_email")

    again = await sign_up(client, username="other.name")

    assert again.status_code == 202
    second = await last_link(client, "sara@example.com", "verify_email")
    assert second != first
    stale = await client.post(f"{API}/auth/verify-email", json={"token": link_token(first)})
    assert stale.status_code == 400


async def test_sign_up_switched_off_answers_404_and_sign_in_still_works(
    database: Database,
) -> None:
    redis = FakeAsyncRedis()
    app = build_app(
        make_settings(signup_enabled=False),
        database=database,
        revocations=RevocationList(redis),
        limiter=RateLimiter(redis),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://platform"
    ) as http:
        response = await http.post(f"{API}/auth/signup", json=signup_body())
        assert response.status_code == 404
        await login(http, "admin", ADMIN_PASSWORD)


# Limits -------------------------------------------------------------------------------


async def test_sign_ups_are_limited_per_client_address(client: httpx.AsyncClient) -> None:
    def attempt(n: int, address: str) -> Any:
        return client.post(
            f"{API}/auth/signup",
            json=signup_body(username=f"user{n}", email=f"user{n}@example.com"),
            headers={"X-Forwarded-For": address},
        )

    for n in range(10):
        assert (await attempt(n, "203.0.113.5")).status_code == 202

    refused = await attempt(10, "203.0.113.5")
    assert refused.status_code == 429
    assert refused.json()["type"] == "urn:quantsim:problem:rate-limited"
    assert refused.json()["retry_after_seconds"] > 0
    # A faked earlier entry does not change the address the gateway appended
    spoofed = await attempt(11, "1.2.3.4, 203.0.113.5")
    assert spoofed.status_code == 429
    assert (await attempt(12, "198.51.100.7")).status_code == 202
    # Sign-in is not limited by this counter
    await login(client, "admin", ADMIN_PASSWORD)


async def test_no_more_than_three_emails_reach_one_address_per_hour(
    client: httpx.AsyncClient, database: Database
) -> None:
    await sign_up(client, account_type="viewer")
    await verify(client, "sara@example.com")

    answers = set()
    for _ in range(5):
        response = await client.post(
            f"{API}/auth/forgot-password", json={"email": "sara@example.com"}
        )
        answers.add((response.status_code, response.text))

    assert len(answers) == 1
    assert len(await mails_to(database, "sara@example.com")) == 3  # verify + 2 resets


async def test_sign_up_fails_closed_when_the_limit_store_is_down(database: Database) -> None:
    class BrokenRedis(FakeAsyncRedis):
        async def incr(self, *args: Any, **kwargs: Any) -> int:
            raise RedisConnectionError("down")

    app = build_app(
        make_settings(),
        database=database,
        revocations=RevocationList(FakeAsyncRedis()),
        limiter=RateLimiter(BrokenRedis()),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://platform"
    ) as http:
        response = await http.post(f"{API}/auth/signup", json=signup_body())
        assert response.status_code == 503
        await login(http, "admin", ADMIN_PASSWORD)
    async with database.transaction() as session:
        count = (await session.execute(text("SELECT count(*) FROM users"))).scalar_one()
    assert count == 1


# Verification and approval ------------------------------------------------------------


async def test_a_viewer_signs_in_right_after_verifying(client: httpx.AsyncClient) -> None:
    await sign_up(client, account_type="viewer")

    before = await try_login(client, "sara.k", PASSWORD)
    assert before.status_code == 403
    assert before.json()["type"] == "urn:quantsim:problem:email-unverified"

    verified = await verify(client, "sara@example.com")
    assert verified.json() == {"status": "verified", "approval_required": False}
    assert (await try_login(client, "sara.k", PASSWORD)).status_code == 200


async def test_a_quant_waits_for_an_admin_then_signs_in(
    client: httpx.AsyncClient, database: Database
) -> None:
    await sign_up(client, account_type="quant")
    verified = await verify(client, "sara@example.com")
    assert verified.json()["approval_required"] is True

    pending = await try_login(client, "sara.k", PASSWORD)
    assert pending.status_code == 403
    assert pending.json()["type"] == "urn:quantsim:problem:approval-pending"
    assert pending.json()["requested_role"] == "quant"
    assert "access_token" not in pending.text

    admin = await login(client, "admin", ADMIN_PASSWORD)
    row = await user_row(database, "sara.k")
    listed = await client.get(f"{API}/users/{row.id}", headers=bearer(admin))
    assert listed.json()["status"] == "pending"

    approved = await client.post(f"{API}/users/{row.id}/approve", headers=bearer(admin))
    assert approved.status_code == 200
    assert approved.json()["status"] == "active"
    assert [t for t, _ in await mails_to(database, "sara@example.com")][-1] == "approved"
    assert "user.approved" in await event_types(database)

    token = await login(client, "sara.k", PASSWORD)
    me = (await client.get(f"{API}/auth/me", headers=bearer(token))).json()
    assert me["role"] == "quant"
    assert me["capabilities"] == sorted(c.value for c in ROLE_CAPABILITIES[Role.QUANT])


async def test_an_admin_rejects_a_pending_analyst(
    client: httpx.AsyncClient, database: Database
) -> None:
    await sign_up(client, account_type="analyst")
    await verify(client, "sara@example.com")
    admin = await login(client, "admin", ADMIN_PASSWORD)
    row = await user_row(database, "sara.k")

    rejected = await client.post(f"{API}/users/{row.id}/reject", headers=bearer(admin))

    assert rejected.json()["status"] == "disabled"
    assert (await try_login(client, "sara.k", PASSWORD)).status_code == 401
    assert "user.rejected" in await event_types(database)


async def test_only_pending_accounts_can_be_approved(
    client: httpx.AsyncClient, database: Database
) -> None:
    await sign_up(client, account_type="quant")  # not verified yet
    admin = await login(client, "admin", ADMIN_PASSWORD)
    row = await user_row(database, "sara.k")
    admin_id = (await client.get(f"{API}/auth/me", headers=bearer(admin))).json()["id"]

    unverified = await client.post(f"{API}/users/{row.id}/approve", headers=bearer(admin))
    already = await client.post(f"{API}/users/{admin_id}/approve", headers=bearer(admin))

    assert unverified.status_code == already.status_code == 409


async def test_a_link_works_once_and_not_for_another_purpose(client: httpx.AsyncClient) -> None:
    await sign_up(client, account_type="viewer")
    link = await last_link(client, "sara@example.com", "verify_email")
    token = link_token(link)

    wrong_purpose = await client.post(
        f"{API}/auth/reset-password", json={"token": token, "password": "another-password-1"}
    )
    first = await client.post(f"{API}/auth/verify-email", json={"token": token})
    second = await client.post(f"{API}/auth/verify-email", json={"token": token})
    altered = await client.post(f"{API}/auth/verify-email", json={"token": token[:-2] + "xx"})

    assert wrong_purpose.status_code == 400
    assert first.status_code == 200
    assert second.status_code == altered.status_code == 400
    assert second.json()["detail"] == "This link is invalid or has expired."


async def test_resend_verification_reveals_nothing(
    client: httpx.AsyncClient, database: Database
) -> None:
    await sign_up(client, account_type="viewer")
    await verify(client, "sara@example.com")
    await sign_up(client, username="omar", email="omar@example.com", account_type="viewer")

    answers = set()
    for email in ("sara@example.com", "omar@example.com", "nobody@example.com"):
        response = await client.post(f"{API}/auth/resend-verification", json={"email": email})
        answers.add((response.status_code, response.text))

    assert answers == {(202, '{"message":"If an account uses that email, we have sent a link."}')}
    assert [t for t, _ in await mails_to(database, "sara@example.com")] == ["verify_email"]
    assert [t for t, _ in await mails_to(database, "omar@example.com")] == [
        "verify_email",
        "verify_email",
    ]
    assert await mails_to(database, "nobody@example.com") == []


# Sign-in by email ---------------------------------------------------------------------


async def test_sign_in_with_the_email_in_any_case(client: httpx.AsyncClient) -> None:
    response = await try_login(client, "Admin@Quantsim.Dev", ADMIN_PASSWORD)

    assert response.status_code == 200
    assert response.json()["user"]["username"] == "admin"


async def test_wrong_passwords_by_username_and_email_add_up_to_one_lockout(
    client: httpx.AsyncClient,
) -> None:
    # The test settings lock after 3 failures
    await try_login(client, "admin", "wrong-password-1")
    await try_login(client, "admin@quantsim.dev", "wrong-password-2")
    await try_login(client, "ADMIN", "wrong-password-3")

    locked = await try_login(client, "admin@quantsim.dev", ADMIN_PASSWORD)
    assert locked.status_code == 429


async def test_an_unverified_account_with_a_wrong_password_gets_the_usual_401(
    client: httpx.AsyncClient,
) -> None:
    await sign_up(client)

    response = await try_login(client, "sara@example.com", "wrong-password-123")

    assert response.status_code == 401
    assert response.json()["type"] == "urn:quantsim:problem:invalid-credentials"


async def test_a_deactivated_account_and_an_unknown_email_look_the_same(
    client: PlatformClient,
) -> None:
    await sign_up(client, account_type="viewer")
    await verify(client, "sara@example.com")
    admin = await login(client, "admin", ADMIN_PASSWORD)
    row = await user_row(client.database, "sara.k")
    await client.post(f"{API}/users/{row.id}/deactivate", headers=bearer(admin))

    deactivated = await try_login(client, "sara@example.com", PASSWORD)
    unknown = await try_login(client, "nobody@example.com", PASSWORD)

    assert deactivated.status_code == unknown.status_code == 401
    assert deactivated.json()["detail"] == unknown.json()["detail"]


async def test_behind_the_tunnel_each_visitor_gets_their_own_limit(
    client: httpx.AsyncClient,
) -> None:
    # Through the tunnel every request comes from the same proxy, but Cloudflare's edge
    # names the real visitor in CF-Connecting-IP
    proxy = {"X-Forwarded-For": "172.18.0.9"}
    for n in range(10):
        response = await client.post(
            f"{API}/auth/signup",
            json=signup_body(username=f"user{n}", email=f"user{n}@example.com"),
            headers={**proxy, "CF-Connecting-IP": "203.0.113.5"},
        )
        assert response.status_code == 202

    blocked = await client.post(
        f"{API}/auth/signup",
        json=signup_body(username="user10", email="user10@example.com"),
        headers={**proxy, "CF-Connecting-IP": "203.0.113.5"},
    )
    other = await client.post(
        f"{API}/auth/signup",
        json=signup_body(username="user11", email="user11@example.com"),
        headers={**proxy, "CF-Connecting-IP": "198.51.100.7"},
    )

    assert blocked.status_code == 429
    assert other.status_code == 202
