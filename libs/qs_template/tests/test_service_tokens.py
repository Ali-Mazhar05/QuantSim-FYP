"""Platform-issued service tokens (ADR 09): verification and the client-credentials
token provider."""

import asyncio
import json
import time
import uuid
from typing import Any

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm
from pydantic import SecretStr

from qs_template import ServiceError, ServiceSettings
from qs_template.auth import Authenticator, Principal, Role, StaticKeys, service_principal
from qs_template.service_client import (
    ClientCredentialsToken,
    ServiceCallError,
    ServiceClient,
    StaticServiceToken,
    service_tokens_from_settings,
)

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
TOKEN_URL = "http://platform:8000/api/platform/service-tokens"
SECRET = SecretStr("s" * 64)


def jwks() -> dict[str, Any]:
    entry: dict[str, Any] = json.loads(RSAAlgorithm.to_jwk(KEY.public_key()))
    entry.update({"kid": "key-1", "alg": "RS256", "use": "sig"})
    return {"keys": [entry]}


def settings(**overrides: Any) -> ServiceSettings:
    values: dict[str, Any] = {
        "service_name": "market",
        "database_url": SecretStr("postgresql+asyncpg://u:p@localhost/market"),
        "auth_leeway_seconds": 0,
    }
    values.update(overrides)
    return ServiceSettings(**values)


def service_token(key: rsa.RSAPrivateKey = KEY, **overrides: Any) -> str:
    now = int(time.time())
    claims: dict[str, Any] = {
        "iss": "quantsim-platform",
        "aud": "quantsim",
        "sub": "service:trading",
        "kind": "service",
        "role": "viewer",
        "jti": uuid.uuid4().hex,
        "iat": now,
        "iat_ms": now * 1000,
        "exp": now + 600,
    }
    claims.update(overrides)
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "key-1"})


def authenticator(**kwargs: Any) -> Authenticator:
    return Authenticator(settings(), jwks=StaticKeys(jwks()), **kwargs)


# Verification -----------------------------------------------------------------------


async def test_accepts_a_service_token_as_a_read_only_service() -> None:
    principal = await authenticator().verify(service_token())

    assert principal.is_service
    assert principal.service_name == "trading"
    assert principal.role is Role.VIEWER
    assert principal.username == "service:trading"


async def test_each_service_has_its_own_fixed_identity() -> None:
    trading = await authenticator().verify(service_token())
    risk = await authenticator().verify(service_token(sub="service:risk"))

    assert trading.user_id != risk.user_id
    assert trading.user_id == service_principal("trading", token_id="x", issued_at=0).user_id


@pytest.mark.parametrize(
    "overrides",
    [
        {"exp": int(time.time()) - 60},
        {"aud": "someone-else"},
        {"iss": "someone-else"},
        {"sub": "service:unknown"},
        {"sub": "trading"},
        {"sub": str(uuid.uuid4())},
        {"kind": "robot"},
        {"role": "admin"},
        {"jti": None},
    ],
    ids=[
        "expired",
        "wrong-audience",
        "wrong-issuer",
        "unknown-service",
        "no-prefix",
        "user-id-subject",
        "wrong-kind",
        "elevated-role",
        "no-jti",
    ],
)
async def test_refuses_bad_service_tokens(overrides: dict[str, Any]) -> None:
    with pytest.raises(ServiceError) as caught:
        await authenticator().verify(service_token(**overrides))

    assert caught.value.status == 401


async def test_refuses_a_forged_service_token() -> None:
    with pytest.raises(ServiceError) as caught:
        await authenticator().verify(service_token(OTHER_KEY))

    assert caught.value.status == 401


async def test_a_user_token_is_never_a_service() -> None:
    user_id = uuid.uuid4()
    token = service_token(sub=str(user_id), kind=None, role="quant", username="quant.demo")

    principal = await authenticator().verify(token)

    assert not principal.is_service
    assert principal.service_name is None
    assert principal.user_id == user_id


async def test_a_user_token_cannot_name_a_service_as_subject() -> None:
    with pytest.raises(ServiceError) as caught:
        await authenticator().verify(service_token(kind=None))

    assert caught.value.status == 401


async def test_revocation_still_applies_to_users_and_services() -> None:
    seen: list[Principal] = []

    async def revoked(principal: Principal) -> bool:
        seen.append(principal)
        return principal.is_service

    auth = authenticator(is_revoked=revoked)
    user = await auth.verify(service_token(sub=str(uuid.uuid4()), kind=None, role="quant"))
    with pytest.raises(ServiceError):
        await auth.verify(service_token())

    assert not user.is_service
    assert [p.is_service for p in seen] == [False, True]


# Token provider ---------------------------------------------------------------------


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class FakeIssuer:
    """The Platform's token endpoint: counts fetches and can be slow or down."""

    def __init__(self, *, expires_in: int = 600) -> None:
        self.expires_in = expires_in
        self.fetches = 0
        self.status = 200
        self.delay = 0.0
        self.bodies: list[dict[str, Any]] = []

    async def handler(self, request: httpx.Request) -> httpx.Response:
        self.fetches += 1
        self.bodies.append(json.loads(request.content))
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.status != 200:
            return httpx.Response(self.status)
        return httpx.Response(
            200,
            json={
                "access_token": f"token-{self.fetches}",
                "token_type": "Bearer",
                "expires_in": self.expires_in,
            },
        )


def provider(issuer: FakeIssuer, clock: FakeClock) -> ClientCredentialsToken:
    return ClientCredentialsToken(
        TOKEN_URL,
        client_id="trading",
        client_secret=SECRET,
        transport=httpx.MockTransport(issuer.handler),
        clock=clock,
    )


async def test_fetches_with_client_credentials_and_caches() -> None:
    issuer, clock = FakeIssuer(), FakeClock()
    tokens = provider(issuer, clock)

    assert await tokens.token() == "token-1"
    clock.now += 300
    assert await tokens.token() == "token-1"

    assert issuer.fetches == 1
    assert issuer.bodies[0] == {
        "grant_type": "client_credentials",
        "client_id": "trading",
        "client_secret": SECRET.get_secret_value(),
    }
    await tokens.close()


async def test_renews_before_expiry() -> None:
    issuer, clock = FakeIssuer(expires_in=600), FakeClock()
    tokens = provider(issuer, clock)
    await tokens.token()

    clock.now += 539
    assert await tokens.token() == "token-1"
    # Within the 60 s margin before expiry: a new one
    clock.now += 2
    assert await tokens.token() == "token-2"
    await tokens.close()


async def test_short_lived_tokens_renew_at_half_their_life() -> None:
    issuer, clock = FakeIssuer(expires_in=60), FakeClock()
    tokens = provider(issuer, clock)
    await tokens.token()

    clock.now += 29
    assert await tokens.token() == "token-1"
    clock.now += 2
    assert await tokens.token() == "token-2"
    await tokens.close()


async def test_a_job_calling_thirty_minutes_later_gets_a_valid_token() -> None:
    issuer, clock = FakeIssuer(), FakeClock()
    tokens = provider(issuer, clock)
    await tokens.token()

    clock.now += 30 * 60

    assert await tokens.token() == "token-2"
    await tokens.close()


async def test_concurrent_callers_share_one_fetch() -> None:
    issuer, clock = FakeIssuer(), FakeClock()
    issuer.delay = 0.05
    tokens = provider(issuer, clock)

    results = await asyncio.gather(*(tokens.token() for _ in range(10)))

    assert set(results) == {"token-1"}
    assert issuer.fetches == 1
    await tokens.close()


async def test_keeps_the_cached_token_when_renewal_fails_before_expiry() -> None:
    issuer, clock = FakeIssuer(), FakeClock()
    tokens = provider(issuer, clock)
    await tokens.token()

    issuer.status = 503
    clock.now += 570
    assert await tokens.token() == "token-1"

    clock.now += 60
    with pytest.raises(ServiceCallError) as caught:
        await tokens.token()
    assert caught.value.status == 503
    assert caught.value.type == "urn:quantsim:problem:service-token-unavailable"
    await tokens.close()


async def test_refused_credentials_are_a_controlled_error() -> None:
    issuer, clock = FakeIssuer(), FakeClock()
    issuer.status = 401
    tokens = provider(issuer, clock)

    with pytest.raises(ServiceCallError) as caught:
        await tokens.token()

    assert caught.value.status == 503
    assert SECRET.get_secret_value() not in str(caught.value.detail)
    await tokens.close()


async def test_service_client_sends_the_fetched_token() -> None:
    issuer, clock = FakeIssuer(), FakeClock()
    seen: list[str] = []

    def market(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers["Authorization"])
        return httpx.Response(200, json={})

    client = ServiceClient(
        "http://market:8000",
        caller="trading",
        tokens=provider(issuer, clock),
        transport=httpx.MockTransport(market),
    )
    await client.get_json("/api/market/instruments")

    assert seen == ["Bearer token-1"]
    await client.close()


# Factory ----------------------------------------------------------------------------


def test_factory_prefers_real_tokens() -> None:
    tokens = service_tokens_from_settings(
        settings(
            service_name="trading",
            environment="test",
            service_token_url=TOKEN_URL,
            service_client_secret=SECRET,
        )
    )

    assert isinstance(tokens, ClientCredentialsToken)


def test_factory_falls_back_to_the_dev_static_token() -> None:
    tokens = service_tokens_from_settings(
        settings(environment="dev", service_token=SecretStr("d" * 40))
    )

    assert isinstance(tokens, StaticServiceToken)


def test_factory_refuses_when_nothing_is_configured() -> None:
    with pytest.raises(ValueError, match="QS_SERVICE_TOKEN_URL"):
        service_tokens_from_settings(settings())


def test_factory_refuses_a_secret_without_a_url() -> None:
    with pytest.raises(ValueError, match="QS_SERVICE_TOKEN_URL is not"):
        service_tokens_from_settings(settings(service_client_secret=SECRET))


def test_empty_compose_values_count_as_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QS_SERVICE_TOKEN_URL", "")
    monkeypatch.setenv("QS_SERVICE_CLIENT_SECRET", "")

    loaded = ServiceSettings(service_name="trading", database_url=SecretStr("postgresql://x/y"))

    assert loaded.service_token_url is None
    assert loaded.service_client_secret is None
