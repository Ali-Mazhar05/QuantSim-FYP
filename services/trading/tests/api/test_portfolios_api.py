"""Portfolio routes over the in-memory store (A-FR-04): a portfolio binds to exactly one
environment, money comes back as decimal strings and the models in canonical JSON."""

import uuid
from typing import Any

import httpx
import pytest
from api_support import (
    API,
    MOMENTUM,
    FakeStore,
    as_role,
    client_for,
    error_locations,
    fake_app,
    portfolio_body,
)

from qs_template.auth import Role

PORTFOLIOS = f"{API}/portfolios"


async def _strategy(http: httpx.AsyncClient) -> str:
    created = await http.post(f"{API}/strategies", json=MOMENTUM, headers=as_role(Role.QUANT))
    assert created.status_code == 201, created.text
    strategy_id: str = created.json()["id"]
    return strategy_id


async def test_a_replay_portfolio_is_created_read_and_listed() -> None:
    owner = uuid.uuid4()
    async with client_for(fake_app(FakeStore())) as http:
        strategy_id = await _strategy(http)
        body = portfolio_body(strategy_id)
        created = await http.post(PORTFOLIOS, json=body, headers=as_role(Role.QUANT, user_id=owner))
        assert created.status_code == 201, created.text
        saved = created.json()
        assert saved["initial_capital"] == "10000.00"
        assert saved["base_currency"] == "USD"
        assert saved["env_type"] == "replay"
        assert saved["replay_environment_id"] == body["replay_environment_id"]
        assert saved["simulation_run_id"] is None and saved["path_index"] is None
        assert saved["cost_model"] == {"fixed": "1.00", "per_share": "0.01", "pct": "0.0005"}
        assert saved["slippage_model"] == {"kind": "volume", "bps": "20"}
        assert saved["strategy_id"] == strategy_id
        assert saved["strategy_name"] == MOMENTUM["name"]
        assert saved["strategy_kind"] == "momentum"
        assert saved["owner_id"] == str(owner)
        assert saved["source_fingerprint"] is None

        analyst = as_role(Role.ANALYST)
        reloaded = await http.get(f"{PORTFOLIOS}/{saved['id']}", headers=analyst)
        assert reloaded.status_code == 200 and reloaded.json() == saved
        assert (await http.get(PORTFOLIOS, headers=analyst)).json() == [saved]


async def test_a_simulation_portfolio_keeps_its_path_and_defaults_its_models() -> None:
    async with client_for(fake_app(FakeStore())) as http:
        strategy_id = await _strategy(http)
        run_id = str(uuid.uuid4())
        created = await http.post(
            PORTFOLIOS,
            json={
                "name": "Median path",
                "strategy_id": strategy_id,
                "initial_capital": 250000,
                "simulation_run_id": run_id,
                "path_index": 0,
            },
            headers=as_role(Role.ADMIN),
        )
        assert created.status_code == 201, created.text
        saved = created.json()
        assert saved["env_type"] == "simulation"
        assert saved["simulation_run_id"] == run_id and saved["path_index"] == 0
        assert saved["replay_environment_id"] is None
        assert saved["initial_capital"] == "250000.00"
        assert saved["cost_model"] == {"fixed": "0", "per_share": "0", "pct": "0"}
        assert saved["slippage_model"] == {"kind": "fixed_bps", "bps": "0"}


@pytest.mark.parametrize(
    ("overrides", "fields"),
    [
        ({"replay_environment_id": None}, {"replay_environment_id", "simulation_run_id"}),
        (
            {"simulation_run_id": str(uuid.uuid4()), "path_index": 0},
            {"replay_environment_id", "simulation_run_id"},
        ),
        (
            {"replay_environment_id": None, "simulation_run_id": str(uuid.uuid4())},
            {"path_index"},
        ),
        ({"path_index": 2}, {"path_index"}),
    ],
    ids=["neither", "both", "simulation-without-path", "replay-with-path"],
)
async def test_a_binding_to_neither_or_both_is_refused(
    overrides: dict[str, Any], fields: set[str]
) -> None:
    store = FakeStore()
    async with client_for(fake_app(store)) as http:
        strategy_id = await _strategy(http)
        body = portfolio_body(strategy_id)
        body.update(overrides)
        body = {k: v for k, v in body.items() if v is not None}
        response = await http.post(PORTFOLIOS, json=body, headers=as_role(Role.QUANT))
        assert {location[-1] for location in error_locations(response)} == fields
        assert response.json()["type"] == "urn:quantsim:problem:validation"
        assert store.portfolios == {}


@pytest.mark.parametrize(
    ("overrides", "location"),
    [
        ({"initial_capital": 1000.5}, ["body", "initial_capital"]),  # a float is refused
        ({"initial_capital": "0"}, ["body", "initial_capital"]),
        ({"initial_capital": "10.001"}, ["body", "initial_capital"]),
        ({"initial_capital": "lots"}, ["body", "initial_capital"]),
        ({"cost_model": {"fixed": "-1"}}, ["body", "cost_model", "fixed"]),
        ({"cost_model": {"flat": "1"}}, ["body", "cost_model", "flat"]),
        ({"slippage_model": {"kind": "magic"}}, ["body", "slippage_model"]),
        ({"slippage_model": {"kind": "fixed_bps", "bps": "10000"}}, ["body", "slippage_model"]),
        ({"path_index": -1}, ["body", "path_index"]),
        ({"name": ""}, ["body", "name"]),
        ({"strategy_id": "nope"}, ["body", "strategy_id"]),
        ({"strategy_id": str(uuid.uuid4())}, ["body", "strategy_id"]),  # no such strategy
    ],
)
async def test_a_bad_body_is_a_422_naming_the_field(
    overrides: dict[str, Any], location: list[str]
) -> None:
    async with client_for(fake_app(FakeStore())) as http:
        strategy_id = await _strategy(http)
        response = await http.post(
            PORTFOLIOS,
            json={**portfolio_body(strategy_id), **overrides},
            headers=as_role(Role.QUANT),
        )
        found = error_locations(response)
        assert any(loc[: len(location)] == location for loc in found), found


async def test_an_unknown_portfolio_is_404() -> None:
    async with client_for(fake_app(FakeStore())) as http:
        response = await http.get(f"{PORTFOLIOS}/{uuid.uuid4()}", headers=as_role(Role.VIEWER))
        assert response.status_code == 404
        assert response.json()["title"] == "Portfolio not found"
