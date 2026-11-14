"""Market environments: create, list and read, in the prototype's shape (FR-MKT-008)."""

import uuid
from datetime import date
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from qs_template import Database
from qs_template.auth import Role
from tests import instrument_support as support
from tests.instrument_support import API, NEW_INSTRUMENT, bearer, insert_bar, make_token

client = support.client
database = support.database
pytestmark = pytest.mark.db

ENVIRONMENTS = f"{API}/environments"


async def add(client: httpx.AsyncClient, symbol: str) -> str:
    admin = bearer(make_token(Role.ADMIN))
    body = {**NEW_INSTRUMENT, "symbol": symbol}
    created = await client.post(f"{API}/instruments", json=body, headers=admin)
    assert created.status_code == 201, created.text
    instrument_id: str = created.json()["id"]
    return instrument_id


def body(ids: list[str], **overrides: Any) -> dict[str, Any]:
    return {
        "name": "US Tech — Historical",
        "type": "historical_replay",
        "universe": "US Technology Basket",
        "instrument_ids": ids,
        "start_date": "2024-01-02",
        "end_date": "2024-03-28",
        "frequency": "daily",
        **overrides,
    }


async def test_a_quant_creates_an_environment_everyone_can_read(
    client: httpx.AsyncClient, database: Database
) -> None:
    first, second = await add(client, "ENVA"), await add(client, "ENVB")
    quant_id = uuid.uuid4()
    quant = bearer(make_token(Role.QUANT, user_id=quant_id))
    created = await client.post(ENVIRONMENTS, json=body([second, first, second]), headers=quant)
    assert created.status_code == 201, created.text
    env = created.json()
    assert env["symbols"] == ["ENVB", "ENVA"]  # given order, duplicates dropped
    assert env["instrument_ids"] == [second, first]
    assert env["created_by"] == str(quant_id)
    assert env["frequency"] == "daily"

    viewer = bearer(make_token(Role.VIEWER))
    listed = (await client.get(ENVIRONMENTS, headers=viewer)).json()
    assert [e["id"] for e in listed] == [env["id"]]
    read = await client.get(f"{ENVIRONMENTS}/{env['id']}", headers=viewer)
    assert read.json() == env
    missing = await client.get(f"{ENVIRONMENTS}/{uuid.uuid4()}", headers=viewer)
    assert missing.status_code == 404


async def test_status_is_ready_only_when_every_instrument_has_data_in_the_window(
    client: httpx.AsyncClient, database: Database
) -> None:
    covered, empty = await add(client, "HASDATA"), await add(client, "NODATA")
    async with database.transaction() as session:
        await insert_bar(session, uuid.UUID(covered), date(2024, 2, 1), "100")
        await insert_bar(session, uuid.UUID(empty), date(2023, 6, 1), "100")  # outside window
    admin = bearer(make_token(Role.ADMIN))
    ready = (await client.post(ENVIRONMENTS, json=body([covered]), headers=admin)).json()
    draft = (await client.post(ENVIRONMENTS, json=body([covered, empty]), headers=admin)).json()
    assert ready["status"] == "ready"
    assert draft["status"] == "draft"


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"end_date": "2024-01-02"}, None),  # same day: not a window
        ({"end_date": "2023-12-29"}, None),  # inverted
        ({"type": "monte_carlo"}, "type"),
        ({"frequency": "weekly"}, "frequency"),
        ({"name": ""}, "name"),
        ({"instrument_ids": []}, "instrument_ids"),
        ({"surprise": 1}, "surprise"),
    ],
)
async def test_bad_bodies_are_422(
    client: httpx.AsyncClient, overrides: dict[str, Any], field: str | None
) -> None:
    instrument_id = await add(client, "BADBODY")
    admin = bearer(make_token(Role.ADMIN))
    response = await client.post(
        ENVIRONMENTS, json=body([instrument_id], **overrides), headers=admin
    )
    assert response.status_code == 422, response.text
    assert response.headers["content-type"].startswith("application/problem+json")
    if field:
        assert field in response.text


async def test_unknown_or_retired_instruments_are_422_and_create_nothing(
    client: httpx.AsyncClient,
) -> None:
    admin = bearer(make_token(Role.ADMIN))
    kept, retired = await add(client, "KEEP"), await add(client, "GONE")
    await client.post(f"{API}/instruments/{retired}/retire", headers=admin)
    unknown = str(uuid.uuid4())
    response = await client.post(ENVIRONMENTS, json=body([kept, retired, unknown]), headers=admin)
    assert response.status_code == 422
    assert set(response.json()["instrument_ids"]) == {retired, unknown}
    assert (await client.get(ENVIRONMENTS, headers=admin)).json() == []


async def test_the_database_itself_refuses_an_inverted_window(database: Database) -> None:
    with pytest.raises(IntegrityError, match="market_environment_window_valid"):
        async with database.transaction() as session:
            await session.execute(
                text(
                    "INSERT INTO market_environment (name, type, universe, instrument_ids,"
                    " start_date, end_date, created_by) VALUES ('x', 'synthetic', 'u',"
                    " '[\"a\"]', '2024-03-01', '2024-01-01', gen_random_uuid())"
                )
            )
