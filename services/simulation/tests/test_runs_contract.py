"""C2 for simulation: the run list and the path tick feed are fixed in OpenAPI now and answer 501
until B18 builds them (the run detail and creation are built: tests/test_runs.py). What is final is
tested: who may call, the parameters, the models and how they relate to the tick contract C1
(B-FR-05, B-US-09)."""

import uuid

import httpx
import pytest

from qs_simulation.api_runs import TICK_EXAMPLE, RunOut, RunSummary, Tick, TickPage
from qs_simulation.main import build_app
from qs_simulation.settings import SimulationSettings
from qs_template.auth import Role
from tests import auth_support as support
from tests.auth_support import API, bearer, make_token
from tests.contract_support import TICK_SCHEMA, tick_problems

client = support.client
RUN = uuid.uuid4()
ROUTES = [f"{API}/runs", f"{API}/runs/{RUN}", f"{API}/runs/{RUN}/ticks"]
NOT_BUILT = [f"{API}/runs", f"{API}/runs/{RUN}/ticks"]  # the detail route is built (B16)


@pytest.mark.parametrize("role", list(Role))
@pytest.mark.parametrize("path", NOT_BUILT)
async def test_every_signed_in_role_reaches_the_routes_and_is_told_it_is_not_built_yet(
    client: httpx.AsyncClient, role: Role, path: str
) -> None:
    response = await client.get(path, headers=bearer(make_token(role)))
    assert response.status_code == 501
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["type"] == "urn:quantsim:problem:not-implemented"


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
    ],
)
async def test_bad_parameters_are_422_before_anything_else(
    client: httpx.AsyncClient, path: str, params: dict[str, str | int]
) -> None:
    response = await client.get(path, params=params, headers=bearer(make_token(Role.VIEWER)))
    assert response.status_code == 422, response.text


async def test_valid_filters_are_accepted(client: httpx.AsyncClient) -> None:
    headers = bearer(make_token(Role.ANALYST))
    for status in ("queued", "running", "completed", "failed"):
        response = await client.get(f"{API}/runs", params={"status": status}, headers=headers)
        assert response.status_code == 501, status  # past validation, to the not-built answer
    response = await client.get(
        f"{API}/runs", params={"instrument": str(uuid.uuid4())}, headers=headers
    )
    assert response.status_code == 501


def test_the_routes_are_in_the_openapi_document(settings: SimulationSettings) -> None:
    spec = build_app(settings).openapi()
    assert {f"{API}/runs", f"{API}/runs/{{run_id}}", f"{API}/runs/{{run_id}}/ticks"} <= set(
        spec["paths"]
    )
    ticks = spec["paths"][f"{API}/runs/{{run_id}}/ticks"]["get"]
    assert "X-Source-Fingerprint" in ticks["responses"]["200"]["headers"]
    names = {p["name"] for p in ticks["parameters"] if p["in"] != "header"}
    assert {"run_id", "path", "after_seq", "limit"} <= names
    listed = spec["paths"][f"{API}/runs"]["get"]
    filters = {p["name"] for p in listed["parameters"] if p["in"] != "header"}
    assert filters == {"status", "instrument"}


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
