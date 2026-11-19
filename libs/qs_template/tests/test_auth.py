import base64
import json
import time
import uuid
from collections.abc import Iterator
from typing import Annotated, Any

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import APIRouter, Depends
from fastapi.testclient import TestClient
from jwt.algorithms import RSAAlgorithm
from pydantic import SecretStr

from qs_template import ServiceError, ServiceSettings, create_app
from qs_template.auth import Authenticator, JwksCache, Principal, Role

JWKS_URL = "http://platform/api/platform/.well-known/jwks.json"
USER_ID = uuid.UUID("2f1c6f3e-4a51-4b0e-9a35-1f0b6a3c9d10")


def new_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def jwk(key: rsa.RSAPrivateKey, kid: str) -> dict[str, Any]:
    entry: dict[str, Any] = json.loads(RSAAlgorithm.to_jwk(key.public_key()))
    entry.update({"kid": kid, "alg": "RS256", "use": "sig"})
    return entry


class FakePlatform:
    """Serves a JWKS document and counts how often it is fetched."""

    def __init__(self) -> None:
        self.keys: dict[str, rsa.RSAPrivateKey] = {"key-1": new_key()}
        self.fetches = 0
        self.down = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.fetches += 1
        if self.down:
            return httpx.Response(503)
        return httpx.Response(200, json={"keys": [jwk(k, kid) for kid, k in self.keys.items()]})

    def token(self, kid: str = "key-1", **overrides: Any) -> str:
        now = int(time.time())
        claims: dict[str, Any] = {
            "iss": "quantsim-platform",
            "aud": "quantsim",
            "sub": str(USER_ID),
            "username": "quant.demo",
            "role": "quant",
            "jti": uuid.uuid4().hex,
            "iat": now,
            "exp": now + 900,
        }
        claims.update(overrides)
        claims = {k: v for k, v in claims.items() if v is not None}
        return jwt.encode(claims, self.keys[kid], algorithm="RS256", headers={"kid": kid})


def unsigned_token(claims: dict[str, Any]) -> str:
    """An "alg: none" token, the classic attempt to skip signature checks."""

    def part(data: dict[str, Any]) -> str:
        return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()

    return f"{part({'alg': 'none', 'typ': 'JWT', 'kid': 'key-1'})}.{part(claims)}."


SETTINGS = ServiceSettings(
    service_name="sample",
    database_url=SecretStr("postgresql+asyncpg://u:p@localhost/sample"),
    auth_jwks_url=JWKS_URL,
    auth_leeway_seconds=0,
)


@pytest.fixture
def platform() -> FakePlatform:
    return FakePlatform()


def make_auth(platform: FakePlatform, **kwargs: Any) -> Authenticator:
    client = httpx.AsyncClient(transport=httpx.MockTransport(platform.handler))
    return Authenticator(SETTINGS, jwks=JwksCache(JWKS_URL, client=client, **kwargs))


@pytest.fixture
def auth(platform: FakePlatform) -> Authenticator:
    return make_auth(platform)


async def test_accepts_a_valid_token(auth: Authenticator, platform: FakePlatform) -> None:
    principal = await auth.verify(platform.token())

    assert principal == Principal(
        user_id=USER_ID,
        username="quant.demo",
        role=Role.QUANT,
        token_id=principal.token_id,
        issued_at=principal.issued_at,
    )


async def test_caches_signing_keys(auth: Authenticator, platform: FakePlatform) -> None:
    for _ in range(5):
        await auth.verify(platform.token())

    assert platform.fetches == 1


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"exp": int(time.time()) - 60}, "expired"),
        ({"aud": "someone-else"}, "not valid"),
        ({"iss": "attacker"}, "not valid"),
        ({"sub": None}, "not valid"),
        ({"jti": None}, "not valid"),
        ({"role": "superuser"}, "valid user and role"),
        ({"sub": "not-a-uuid"}, "valid user and role"),
    ],
)
async def test_rejects_invalid_claims(
    auth: Authenticator, platform: FakePlatform, overrides: dict[str, Any], reason: str
) -> None:
    with pytest.raises(ServiceError) as error:
        await auth.verify(platform.token(**overrides))

    assert error.value.status == 401
    assert reason in str(error.value)


async def test_rejects_a_forged_signature(auth: Authenticator, platform: FakePlatform) -> None:
    forger = new_key()
    claims = jwt.decode(platform.token(), options={"verify_signature": False})
    forged = jwt.encode(claims, forger, algorithm="RS256", headers={"kid": "key-1"})

    with pytest.raises(ServiceError) as error:
        await auth.verify(forged)

    assert error.value.status == 401


async def test_rejects_tokens_not_signed_with_rs256(auth: Authenticator) -> None:
    hs256 = jwt.encode(
        {"sub": str(USER_ID)}, "a-shared-secret-of-at-least-32-bytes", algorithm="HS256"
    )
    unsigned = unsigned_token({"sub": str(USER_ID)})

    for token in (hs256, unsigned, "not-a-token"):
        with pytest.raises(ServiceError) as error:
            await auth.verify(token)
        assert error.value.status == 401


async def test_picks_up_a_rotated_key(platform: FakePlatform) -> None:
    auth = make_auth(platform, min_refresh_seconds=0)
    await auth.verify(platform.token())

    platform.keys["key-2"] = new_key()
    principal = await auth.verify(platform.token(kid="key-2"))

    assert principal.user_id == USER_ID
    assert platform.fetches == 2


async def test_unknown_keys_cannot_force_constant_refetches(
    auth: Authenticator, platform: FakePlatform
) -> None:
    await auth.verify(platform.token())
    platform.keys["key-9"] = new_key()

    for _ in range(10):
        with pytest.raises(ServiceError):
            await auth.verify(platform.token(kid="key-9"))

    assert platform.fetches == 1


async def test_fails_closed_when_keys_cannot_be_fetched(
    auth: Authenticator, platform: FakePlatform
) -> None:
    platform.down = True

    with pytest.raises(ServiceError) as error:
        await auth.verify(platform.token())

    assert error.value.status == 503


async def test_keeps_working_on_cached_keys_when_platform_goes_down(
    platform: FakePlatform,
) -> None:
    auth = make_auth(platform, ttl_seconds=0)
    await auth.verify(platform.token())
    platform.down = True

    principal = await auth.verify(platform.token())

    assert principal.user_id == USER_ID


async def test_honours_revocation(platform: FakePlatform) -> None:
    client = httpx.AsyncClient(transport=httpx.MockTransport(platform.handler))

    async def revoked(principal: Principal) -> bool:
        return principal.user_id == USER_ID

    auth = Authenticator(SETTINGS, jwks=JwksCache(JWKS_URL, client=client), is_revoked=revoked)

    with pytest.raises(ServiceError) as error:
        await auth.verify(platform.token())

    assert "revoked" in str(error.value)


@pytest.fixture
def client(auth: Authenticator) -> Iterator[TestClient]:
    router = APIRouter()

    @router.get("/me")
    async def me(user: Annotated[Principal, Depends(auth.principal)]) -> dict[str, str]:
        return {"user": str(user.user_id), "role": user.role}

    @router.post("/admin-only", dependencies=[Depends(auth.require(Role.ADMIN))])
    async def admin_only() -> dict[str, bool]:
        return {"ok": True}

    with TestClient(create_app(SETTINGS, routers=[router])) as test_client:
        yield test_client


def test_endpoint_returns_the_caller(client: TestClient, platform: FakePlatform) -> None:
    response = client.get("/api/sample/me", headers={"Authorization": f"Bearer {platform.token()}"})

    assert response.status_code == 200
    assert response.json() == {"user": str(USER_ID), "role": "quant"}


@pytest.mark.parametrize("header", [None, "", "Basic abc", "Bearer", "Bearer not-a-token"])
def test_endpoint_refuses_missing_or_bad_credentials(
    client: TestClient, header: str | None
) -> None:
    headers = {"Authorization": header} if header is not None else {}

    response = client.get("/api/sample/me", headers=headers)

    assert response.status_code == 401
    assert response.headers["content-type"] == "application/problem+json"


def test_role_check_allows_the_listed_role(client: TestClient, platform: FakePlatform) -> None:
    token = platform.token(role="admin")

    response = client.post("/api/sample/admin-only", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200


@pytest.mark.parametrize("role", ["quant", "analyst", "viewer"])
def test_role_check_refuses_other_roles(
    client: TestClient, platform: FakePlatform, role: str
) -> None:
    token = platform.token(role=role)

    response = client.post("/api/sample/admin-only", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 403
    assert response.json()["type"] == "urn:quantsim:problem:forbidden"


def test_needs_a_jwks_url() -> None:
    settings = ServiceSettings(
        service_name="sample", database_url=SecretStr("postgresql+asyncpg://u:p@localhost/s")
    )

    with pytest.raises(ValueError, match="QS_AUTH_JWKS_URL"):
        Authenticator(settings)
