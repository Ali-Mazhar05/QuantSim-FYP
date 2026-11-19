"""C2 for market: who may call the replay feed and activation, the parameters, the models, the
list filters and the OpenAPI document, on a real database (B-FR-03, B-FR-05). What the feed returns
and how activation behaves is tested in test_replay_feed.py."""

import uuid
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from qs_market.api_data import DEFAULT_LIMIT, MAX_LIMIT
from qs_market.api_feeds import TICK_EXAMPLE, ActivationOut, Tick, TickPage
from qs_template import Database
from qs_template.auth import Role
from tests import instrument_support as support
from tests.contract_support import TICK_SCHEMA, tick_problems
from tests.instrument_support import API, bearer, make_token
from tests.read_support import add_instrument
from tests.test_correlation_api import OVERLAP, both_loaded

client = support.client
database = support.database
pytestmark = pytest.mark.db


async def make_environment(
    http: httpx.AsyncClient,
    instrument: uuid.UUID,
    *,
    kind: str = "historical_replay",
    frequency: str = "daily",
    role: Role = Role.QUANT,
    user: uuid.UUID | None = None,
    instruments: list[uuid.UUID] | None = None,
    start: str = "2020-01-02",
    end: str = "2020-12-31",
) -> dict[str, Any]:
    response = await http.post(
        f"{API}/environments",
        json={
            "name": f"{kind} {frequency}",
            "type": kind,
            "universe": "Big tech",
            "instrument_ids": [str(i) for i in instruments or [instrument]],
            "start_date": start,
            "end_date": end,
            "frequency": frequency,
        },
        headers=bearer(make_token(role, user_id=user)),
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


@pytest.fixture
async def instrument(database: Database) -> uuid.UUID:
    return await add_instrument(database, "AAPL")


@pytest.fixture
async def ready(client: httpx.AsyncClient, database: Database) -> dict[str, Any]:
    """A daily replay environment over two instruments with ingested data: status ready."""
    ids = await both_loaded(database)
    environment = await make_environment(
        client,
        ids["AAPL"],
        instruments=[ids["AAPL"], ids["PEER"]],
        start=OVERLAP["start"],
        end=OVERLAP["end"],
    )
    assert environment["status"] == "ready"
    return environment


async def listed(http: httpx.AsyncClient, **params: str) -> list[dict[str, Any]]:
    response = await http.get(
        f"{API}/environments", params=params, headers=bearer(make_token(Role.VIEWER))
    )
    assert response.status_code == 200, response.text
    body: list[dict[str, Any]] = response.json()
    return body


async def test_the_environment_list_filters_by_type_and_owner(
    client: httpx.AsyncClient, instrument: uuid.UUID
) -> None:
    ann, bob = uuid.uuid4(), uuid.uuid4()
    replay_a = await make_environment(client, instrument, user=ann)
    synthetic_a = await make_environment(client, instrument, kind="synthetic", user=ann)
    replay_b = await make_environment(client, instrument, role=Role.ADMIN, user=bob)

    def ids(rows: list[dict[str, Any]]) -> set[str]:
        return {row["id"] for row in rows}

    assert ids(await listed(client)) == {replay_a["id"], synthetic_a["id"], replay_b["id"]}
    assert ids(await listed(client, type="synthetic")) == {synthetic_a["id"]}
    assert ids(await listed(client, type="historical_replay")) == {replay_a["id"], replay_b["id"]}
    assert ids(await listed(client, owner=str(ann))) == {replay_a["id"], synthetic_a["id"]}
    assert ids(await listed(client, type="historical_replay", owner=str(bob))) == {replay_b["id"]}
    assert await listed(client, owner=str(uuid.uuid4())) == []


@pytest.mark.parametrize("params", [{"type": "nonsense"}, {"owner": "not-a-uuid"}])
async def test_a_bad_filter_is_422(client: httpx.AsyncClient, params: dict[str, str]) -> None:
    response = await client.get(
        f"{API}/environments", params=params, headers=bearer(make_token(Role.VIEWER))
    )
    assert response.status_code == 422


@pytest.mark.parametrize("role", list(Role))
async def test_every_signed_in_role_may_read_the_feed(
    client: httpx.AsyncClient, ready: dict[str, Any], role: Role
) -> None:
    response = await client.get(
        f"{API}/environments/{ready['id']}/ticks", headers=bearer(make_token(role))
    )
    assert response.status_code == 200, response.text
    assert response.headers["X-Source-Fingerprint"].startswith("xxh3:")
    assert response.json()["items"], "the page has ticks"


async def test_the_feed_says_why_an_environment_has_none(
    client: httpx.AsyncClient, instrument: uuid.UUID
) -> None:
    viewer = bearer(make_token(Role.VIEWER))
    unknown = await client.get(f"{API}/environments/{uuid.uuid4()}/ticks", headers=viewer)
    assert unknown.status_code == 404
    hourly = await make_environment(client, instrument, frequency="hourly")
    refused = await client.get(f"{API}/environments/{hourly['id']}/ticks", headers=viewer)
    assert refused.status_code == 422
    assert refused.json()["type"] == "urn:quantsim:problem:unsupported-frequency"
    assert "hourly" in refused.json()["detail"]
    synthetic = await make_environment(client, instrument, kind="synthetic")
    other = await client.get(f"{API}/environments/{synthetic['id']}/ticks", headers=viewer)
    assert other.status_code == 422
    assert other.json()["type"] == "urn:quantsim:problem:not-a-replay-environment"


@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": MAX_LIMIT + 1},
        {"after_seq": -1},
        {"limit": "many"},
        {"after_seq": "first"},
    ],
)
async def test_bad_paging_parameters_are_422(
    client: httpx.AsyncClient, params: dict[str, str | int]
) -> None:
    response = await client.get(
        f"{API}/environments/{uuid.uuid4()}/ticks",
        params=params,
        headers=bearer(make_token(Role.VIEWER)),
    )
    assert response.status_code == 422, response.text


async def test_the_page_limits_are_accepted_at_their_edges(
    client: httpx.AsyncClient, ready: dict[str, Any]
) -> None:
    for params in ({"limit": 1}, {"limit": MAX_LIMIT, "after_seq": 0}, {"after_seq": 123456}):
        response = await client.get(
            f"{API}/environments/{ready['id']}/ticks",
            params=params,
            headers=bearer(make_token(Role.VIEWER)),
        )
        assert response.status_code == 200, params


async def test_only_quants_and_admins_may_activate(
    client: httpx.AsyncClient, ready: dict[str, Any]
) -> None:
    url = f"{API}/environments/{ready['id']}/activate"
    for role in (Role.VIEWER, Role.ANALYST):
        assert (await client.post(url, headers=bearer(make_token(role)))).status_code == 403, role
    for role in (Role.QUANT, Role.ADMIN):
        response = await client.post(url, headers=bearer(make_token(role)))
        assert response.status_code == 200, (role, response.text)
        assert response.json()["status"] == "active"
    assert (await client.post(url)).status_code == 401


async def test_activation_refuses_what_cannot_be_replayed(
    client: httpx.AsyncClient, instrument: uuid.UUID
) -> None:
    quant = bearer(make_token(Role.QUANT))
    assert (
        await client.post(f"{API}/environments/{uuid.uuid4()}/activate", headers=quant)
    ).status_code == 404
    for frequency in ("hourly", "tick"):
        environment = await make_environment(client, instrument, frequency=frequency)
        response = await client.post(
            f"{API}/environments/{environment['id']}/activate", headers=quant
        )
        assert response.status_code == 422, frequency
        assert response.json()["type"] == "urn:quantsim:problem:unsupported-frequency"


async def test_unauthenticated_callers_are_refused_on_the_feed(
    client: httpx.AsyncClient,
) -> None:
    url = f"{API}/environments/{uuid.uuid4()}/ticks"
    assert (await client.get(url)).status_code == 401
    forged = bearer(make_token(Role.QUANT, forged=True))
    assert (await client.get(url, headers=forged)).status_code == 401


def _spec(client: httpx.AsyncClient) -> dict[str, Any]:
    app = client._transport.app  # type: ignore[attr-defined]
    assert isinstance(app, FastAPI)
    spec: dict[str, Any] = app.openapi()
    return spec


async def test_the_openapi_document_fixes_the_feed_contract(client: httpx.AsyncClient) -> None:
    spec = _spec(client)
    ticks = spec["paths"][f"{API}/environments/{{environment_id}}/ticks"]["get"]
    assert "X-Source-Fingerprint" in ticks["responses"]["200"]["headers"]
    assert {p["name"] for p in ticks["parameters"] if p["in"] != "header"} == {
        "environment_id",
        "after_seq",
        "limit",
    }
    by_name = {p["name"]: p["schema"] for p in ticks["parameters"]}
    assert by_name["limit"]["maximum"] == MAX_LIMIT and by_name["limit"]["default"] == DEFAULT_LIMIT
    assert by_name["after_seq"]["minimum"] == 0
    assert {"401", "403", "404", "422"} <= set(ticks["responses"])
    assert f"{API}/environments/{{environment_id}}/activate" in spec["paths"]
    listing = spec["paths"][f"{API}/environments"]["get"]
    assert {p["name"] for p in listing["parameters"] if p["in"] != "header"} == {"type", "owner"}


async def test_the_tick_model_is_the_tick_contract(client: httpx.AsyncClient) -> None:
    model = _spec(client)["components"]["schemas"]["Tick"]
    assert set(model["properties"]) == set(TICK_SCHEMA["properties"])
    assert set(model["required"]) == set(TICK_SCHEMA["required"])


def test_the_worked_examples_follow_the_tick_contract() -> None:
    assert tick_problems(TICK_EXAMPLE) == []
    page = TickPage.model_json_schema()["examples"][0]
    assert all(tick_problems(tick) == [] for tick in page["items"])
    assert Tick.model_validate(TICK_EXAMPLE).model_dump(mode="json")["ts"] == TICK_EXAMPLE["ts"]
    activation = ActivationOut.model_json_schema()["examples"][0]
    assert ActivationOut.model_validate(activation).missing_session_count == 0
