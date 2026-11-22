"""Service tokens issued to calling services (ADR 09). No database is needed: the route
reads its clients from settings and counts bad secrets in Redis."""

from collections.abc import AsyncIterator
from typing import Any

import httpx
import jwt
import pytest
from fakeredis import FakeAsyncRedis
from pydantic import SecretStr, ValidationError

from qs_platform.limits import RateLimiter
from qs_platform.main import build_app
from qs_template import Database
from qs_template.auth import Authenticator, Role, StaticKeys
from qs_template.revocation import RevocationList
from tests.conftest import make_settings

TRADING_SECRET = "t" * 64
RISK_SECRET = "r" * 64
URL = "/api/platform/service-tokens"


def settings(**overrides: Any) -> Any:
    values: dict[str, Any] = {
        "service_client_secrets": SecretStr(f"trading={TRADING_SECRET},risk={RISK_SECRET}"),
    }
    values.update(overrides)
    return make_settings(**values)


@pytest.fixture
async def http() -> AsyncIterator[httpx.AsyncClient]:
    redis = FakeAsyncRedis()
    config = settings()
    app = build_app(
        config,
        database=Database(config),
        revocations=RevocationList(redis),
        limiter=RateLimiter(redis),
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://platform") as client:
        yield client


async def request_token(
    http: httpx.AsyncClient, client_id: str = "trading", secret: str = TRADING_SECRET
) -> httpx.Response:
    return await http.post(
        URL,
        json={"grant_type": "client_credentials", "client_id": client_id, "client_secret": secret},
    )


async def jwks(http: httpx.AsyncClient) -> StaticKeys:
    return StaticKeys((await http.get("/api/platform/.well-known/jwks.json")).json())


async def test_issues_a_short_lived_service_token(http: httpx.AsyncClient) -> None:
    response = await request_token(http)

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["token_type"] == "Bearer"
    assert body["expires_in"] == 600
    claims = jwt.decode(body["access_token"], options={"verify_signature": False})
    assert claims["sub"] == "service:trading"
    assert claims["kind"] == "service"
    assert claims["role"] == "viewer"
    assert claims["aud"] == "quantsim"
    assert claims["iss"] == "quantsim-platform"
    assert claims["exp"] - claims["iat"] == 600
    assert claims["jti"]
    assert "username" not in claims


async def test_issued_tokens_verify_as_a_service_in_other_services(
    http: httpx.AsyncClient,
) -> None:
    token = (await request_token(http)).json()["access_token"]
    auth = Authenticator(make_settings(), jwks=await jwks(http))

    principal = await auth.verify(token)

    assert principal.is_service
    assert principal.service_name == "trading"
    assert principal.role is Role.VIEWER


async def test_a_service_token_reads_what_a_viewer_reads(http: httpx.AsyncClient) -> None:
    token = (await request_token(http)).json()["access_token"]

    response = await http.get("/api/platform/users", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 403


@pytest.mark.parametrize(
    ("client_id", "secret"),
    [
        ("trading", "wrong-secret"),
        ("trading", RISK_SECRET),
        ("market", TRADING_SECRET),
        ("nobody", TRADING_SECRET),
    ],
    ids=["wrong-secret", "another-service-secret", "unconfigured-service", "unknown-client"],
)
async def test_refuses_bad_client_credentials(
    http: httpx.AsyncClient, client_id: str, secret: str
) -> None:
    response = await request_token(http, client_id, secret)

    assert response.status_code == 401
    assert response.json()["type"] == "urn:quantsim:problem:invalid-client"
    assert "access_token" not in response.text


async def test_refuses_other_grant_types(http: httpx.AsyncClient) -> None:
    response = await http.post(
        URL, json={"grant_type": "password", "client_id": "trading", "client_secret": "x"}
    )

    assert response.status_code == 422


async def test_blocks_an_address_after_repeated_bad_secrets(http: httpx.AsyncClient) -> None:
    # make_settings allows 3 failures
    for _ in range(3):
        assert (await request_token(http, secret="wrong")).status_code == 401

    blocked = await request_token(http)

    assert blocked.status_code == 429
    assert blocked.json()["type"] == "urn:quantsim:problem:rate-limited"


async def test_good_secrets_are_not_counted(http: httpx.AsyncClient) -> None:
    for _ in range(5):
        assert (await request_token(http)).status_code == 200


def test_client_secrets_name_known_services_only() -> None:
    with pytest.raises(ValidationError, match="known services"):
        settings(service_client_secrets=SecretStr(f"robot={TRADING_SECRET}"))


def test_client_secrets_must_be_long() -> None:
    with pytest.raises(ValidationError, match="at least 32"):
        settings(service_client_secrets=SecretStr("trading=short"))


def test_errors_never_show_a_secret() -> None:
    with pytest.raises(ValidationError) as caught:
        settings(service_client_secrets=SecretStr("trading=short-secret-value"))

    assert "short-secret-value" not in str(caught.value)


def test_an_empty_secret_disables_that_client() -> None:
    config = settings(service_client_secrets=SecretStr(f"trading=,risk={RISK_SECRET}"))

    assert set(config.service_client_digests) == {"risk"}


def test_only_digests_of_the_secrets_are_kept() -> None:
    digests = settings().service_client_digests

    assert set(digests) == {"trading", "risk"}
    assert TRADING_SECRET.encode() not in digests.values()


async def test_no_clients_configured_refuses_everyone() -> None:
    config = make_settings()
    redis = FakeAsyncRedis()
    app = build_app(
        config,
        database=Database(config),
        revocations=RevocationList(redis),
        limiter=RateLimiter(redis),
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://platform") as client:
        assert (await request_token(client)).status_code == 401
