"""C2 for simulation: who may call the run routes, the parameters, the models and how they relate to
the tick contract C1 (B-FR-05, B-US-09). The database-backed behaviour is in tests/test_reads.py."""

import uuid
from datetime import UTC, date, datetime

import httpx
import pytest

from qs_simulation.api_runs import (
    TICK_EXAMPLE,
    RunOut,
    RunSummary,
    Tick,
    TickPage,
)
from qs_simulation.main import build_app
from qs_simulation.reads import require_path
from qs_simulation.settings import SimulationSettings
from qs_template.auth import Role
from qs_template.errors import ServiceError
from tests import auth_support as support
from tests.auth_support import API, bearer, make_token
from tests.contract_support import TICK_SCHEMA, tick_problems

client = support.client
RUN = uuid.uuid4()
ROUTES = [f"{API}/runs", f"{API}/runs/{RUN}", f"{API}/runs/{RUN}/ticks?path=0"]


@pytest.mark.parametrize("path", ROUTES)
async def test_anonymous_and_forged_callers_are_refused(
    client: httpx.AsyncClient, path: str
) -> None:
    assert (await client.get(path)).status_code == 401
    forged = bearer(make_token(Role.QUANT, forged=True))
    assert (await client.get(path, headers=forged)).status_code == 401


@pytest.mark.parametrize(
    ("path", "params"),
    [
        (f"{API}/runs", {"status": "bogus"}),
        (f"{API}/runs", {"instrument": "not-a-uuid"}),
        (f"{API}/runs/not-a-uuid", {}),
        (f"{API}/runs/{RUN}/ticks", {"limit": 0}),
        (f"{API}/runs/{RUN}/ticks", {"limit": 2001}),
        (f"{API}/runs/{RUN}/ticks", {"after_seq": -1}),
        (f"{API}/runs/{RUN}/ticks", {"path": -1}),
        (f"{API}/runs/{RUN}/ticks", {"path": "first"}),
        (f"{API}/runs/{RUN}/ticks", {"after_seq": 0}),
    ],
)
async def test_bad_parameters_are_422_before_anything_else(
    client: httpx.AsyncClient, path: str, params: dict[str, str | int]
) -> None:
    response = await client.get(path, params=params, headers=bearer(make_token(Role.VIEWER)))
    assert response.status_code == 422, response.text


def test_the_routes_are_in_the_openapi_document(settings: SimulationSettings) -> None:
    spec = build_app(settings).openapi()
    assert {f"{API}/runs", f"{API}/runs/{{run_id}}", f"{API}/runs/{{run_id}}/ticks"} <= set(
        spec["paths"]
    )
    ticks = spec["paths"][f"{API}/runs/{{run_id}}/ticks"]["get"]
    assert "X-Source-Fingerprint" in ticks["responses"]["200"]["headers"]
    names = {p["name"] for p in ticks["parameters"] if p["in"] != "header"}
    assert {"run_id", "path", "after_seq", "limit"} <= names
    path = next(p for p in ticks["parameters"] if p["name"] == "path")
    assert path["required"] is True and "default" not in path["schema"]
    listed = spec["paths"][f"{API}/runs"]["get"]
    filters = {p["name"] for p in listed["parameters"] if p["in"] != "header"}
    assert filters == {"status", "instrument", "limit", "cursor"}


def test_the_tick_model_is_the_tick_contract(settings: SimulationSettings) -> None:
    model = build_app(settings).openapi()["components"]["schemas"]["Tick"]
    assert set(model["properties"]) == set(TICK_SCHEMA["properties"])
    assert set(model["required"]) == set(TICK_SCHEMA["required"])


def test_the_worked_examples_follow_the_tick_contract() -> None:
    assert tick_problems(TICK_EXAMPLE) == []
    page = TickPage.model_json_schema()["examples"][0]
    assert all(tick_problems(tick) == [] for tick in page["items"])
    assert Tick.model_validate(TICK_EXAMPLE).model_dump(mode="json")["ts"] == TICK_EXAMPLE["ts"]


def test_a_synthetic_tick_needs_its_path_and_a_run_names_its_lineage() -> None:
    missing = {k: v for k, v in TICK_EXAMPLE.items() if k != "path_index"}
    assert any("path_index" in p for p in tick_problems(missing))
    assert {"parent_run_id", "scenario", "median_path_index"} <= set(RunSummary.model_fields)
    assert {"statistics", "progress", "seed", "storage_mode"} <= set(RunOut.model_fields)


async def test_a_missing_path_is_422_and_names_the_parameter(client: httpx.AsyncClient) -> None:
    response = await client.get(f"{API}/runs/{RUN}/ticks", headers=bearer(make_token(Role.VIEWER)))
    assert response.status_code == 422, response.text
    assert ["query", "path"] in [e["location"] for e in response.json()["errors"]]


@pytest.mark.parametrize(
    ("env_type", "session_date", "path_index"),
    [("synthetic", None, 0), ("synthetic", None, 7), ("replay", date(2021, 1, 4), None)],
)
def test_a_serialised_tick_model_follows_the_contract(
    env_type: str, session_date: date | None, path_index: int | None
) -> None:
    tick = Tick(
        env_id=uuid.uuid4(),
        env_type=env_type,
        source_fingerprint="xxh3:9d1e0c7b5a3f2e4d6c8b0a1f3e5d7c9b",
        seq=1,
        session=0,
        session_date=session_date,
        ts=datetime(2021, 1, 4, 21, 0, tzinfo=UTC),
        instrument_id=uuid.uuid4(),
        symbol="AAPL",
        open="132.4100000000",
        high="132.4100000000",
        low="132.4100000000",
        close="132.4100000000",
        volume="0.00000000",
        path_index=path_index,
    ).model_dump(mode="json")
    assert "session_date" in tick
    assert tick_problems(tick) == []


def test_a_path_outside_the_run_is_404() -> None:
    require_path(0, 3)
    require_path(2, 3)
    with pytest.raises(ServiceError) as caught:
        require_path(3, 3)
    assert caught.value.status == 404
    assert caught.value.type == "urn:quantsim:problem:not-found"
