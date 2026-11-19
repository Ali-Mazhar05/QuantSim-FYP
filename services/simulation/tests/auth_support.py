"""Signed tokens for every role and an app wired with the matching public key, for tests that call
the HTTP API. The same approach as the market service's tests."""

import json
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fakeredis import FakeAsyncRedis
from jwt.algorithms import RSAAlgorithm

from qs_simulation.main import build_app
from qs_simulation.settings import SimulationSettings
from qs_template import Database
from qs_template.auth import Authenticator, Role, StaticKeys
from qs_template.revocation import RevocationList

API = "/api/simulation"
KEY_ID = "test-key-1"
_PRIVATE = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_FORGED = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _jwks() -> dict[str, Any]:
    public: dict[str, Any] = json.loads(RSAAlgorithm.to_jwk(_PRIVATE.public_key()))
    public.update({"kid": KEY_ID, "alg": "RS256", "use": "sig"})
    return {"keys": [public]}


def make_token(role: Role, *, forged: bool = False, user_id: uuid.UUID | None = None) -> str:
    now = int(time.time())
    claims = {
        "sub": str(user_id or uuid.uuid4()),
        "username": f"{role.value}.user",
        "role": role.value,
        "jti": uuid.uuid4().hex,
        "iat": now,
        "exp": now + 600,
        "iss": "quantsim-platform",
        "aud": "quantsim",
    }
    key = _FORGED if forged else _PRIVATE
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": KEY_ID})


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def client(settings: SimulationSettings) -> AsyncIterator[httpx.AsyncClient]:
    app = build_app(
        settings,
        database=Database(settings),
        revocations=RevocationList(FakeAsyncRedis()),
        authenticator=Authenticator(settings, jwks=StaticKeys(_jwks())),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://simulation"
    ) as http:
        yield http
