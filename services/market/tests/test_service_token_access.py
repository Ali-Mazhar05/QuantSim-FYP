"""A platform-issued service token (ADR 09) reads what the other services need and writes nothing
(DL-015): the replay feed, the bars and the correlation matrix answer it; activation and replay
sessions refuse it. It is the token the simulation and trading workers send."""

import time
import uuid
from typing import Any

import httpx
import jwt
import pytest

from tests import instrument_support as support
from tests import test_feed_contract_api as contract
from tests.instrument_support import _PRIVATE, API, KEY_ID, bearer

client = support.client
database = support.database
ready = contract.ready
pytestmark = pytest.mark.db


def service_token(name: str = "simulation") -> str:
    now = int(time.time())
    claims: dict[str, Any] = {
        "iss": "quantsim-platform",
        "aud": "quantsim",
        "sub": f"service:{name}",
        "kind": "service",
        "role": "viewer",
        "jti": uuid.uuid4().hex,
        "iat": now,
        "iat_ms": now * 1000,
        "exp": now + 600,
    }
    return jwt.encode(claims, _PRIVATE, algorithm="RS256", headers={"kid": KEY_ID})


async def test_a_service_token_reads_the_feed_the_bars_and_the_correlations(
    client: httpx.AsyncClient, ready: dict[str, Any]
) -> None:
    headers = bearer(service_token())
    ticks = await client.get(f"{API}/environments/{ready['id']}/ticks", headers=headers)
    assert ticks.status_code == 200 and ticks.json()["items"]
    first = ready["instrument_ids"][0]
    bars = await client.get(f"{API}/instruments/{first}/bars", headers=headers)
    assert bars.status_code == 200 and bars.json()["items"]
    body = {
        "instrument_ids": ready["instrument_ids"],
        "windows": [{"start": ready["start_date"], "end": ready["end_date"]}],
        "min_observations": 5,
    }
    matrix = await client.post(f"{API}/correlations", json=body, headers=headers)
    assert matrix.status_code == 200, matrix.text


async def test_a_service_token_cannot_activate_or_drive_a_replay(
    client: httpx.AsyncClient, ready: dict[str, Any]
) -> None:
    headers = bearer(service_token("trading"))
    activate = await client.post(f"{API}/environments/{ready['id']}/activate", headers=headers)
    assert activate.status_code == 403
    session = await client.post(
        f"{API}/replay-sessions", json={"environment_id": ready["id"]}, headers=headers
    )
    assert session.status_code == 403


async def test_a_token_naming_an_unknown_service_is_refused(
    client: httpx.AsyncClient, ready: dict[str, Any]
) -> None:
    response = await client.get(
        f"{API}/environments/{ready['id']}/ticks", headers=bearer(service_token("mallory"))
    )
    assert response.status_code == 401
