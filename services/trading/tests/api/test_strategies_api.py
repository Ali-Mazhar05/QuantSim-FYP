"""Strategy routes over the in-memory store (A-FR-01): every kind saves and reloads, a bad
parameter is a 422 naming the field, and a strategy that has run is not edited."""

import uuid
from typing import Any

import pytest
from api_support import API, MOMENTUM, FakeStore, as_role, client_for, error_locations, fake_app

from qs_template.auth import Role

STRATEGIES = f"{API}/strategies"

EVERY_KIND: list[dict[str, Any]] = [
    {"name": "Hold", "kind": "buy_and_hold", "params": {}},
    {
        "name": "Cross",
        "kind": "ma_crossover",
        "params": {"fast": 5, "slow": 20},
    },
    MOMENTUM,
    {"name": "Revert", "kind": "mean_reversion", "params": {}},
]


@pytest.mark.parametrize("body", EVERY_KIND, ids=lambda b: b["kind"])
async def test_every_kind_saves_and_reloads_with_defaults_filled_in(body: dict[str, Any]) -> None:
    owner = uuid.uuid4()
    async with client_for(fake_app(FakeStore())) as http:
        created = await http.post(STRATEGIES, json=body, headers=as_role(Role.QUANT, user_id=owner))
        assert created.status_code == 201, created.text
        saved = created.json()
        assert saved["kind"] == body["kind"] and saved["name"] == body["name"]
        assert saved["owner_id"] == str(owner)
        # Every given value is kept, every omitted one is filled with its default
        for name, value in body["params"].items():
            assert saved["params"][name] == value
        assert "cash_buffer" in saved["params"]

        viewer = as_role(Role.VIEWER)
        reloaded = await http.get(f"{STRATEGIES}/{saved['id']}", headers=viewer)
        assert reloaded.status_code == 200
        assert reloaded.json() == saved
        assert (await http.get(STRATEGIES, headers=viewer)).json() == [saved]


async def test_the_list_is_newest_first() -> None:
    async with client_for(fake_app(FakeStore())) as http:
        quant = as_role(Role.QUANT)
        ids = [
            (await http.post(STRATEGIES, json={**MOMENTUM, "name": f"S{i}"}, headers=quant)).json()[
                "id"
            ]
            for i in range(3)
        ]
        listed = (await http.get(STRATEGIES, headers=quant)).json()
        assert [s["id"] for s in listed] == ids[::-1]


@pytest.mark.parametrize(
    ("body", "location"),
    [
        ({**MOMENTUM, "kind": "astrology"}, ["body", "kind"]),
        (
            {**MOMENTUM, "params": {**MOMENTUM["params"], "lookback": 0}},
            ["body", "params", "lookback"],
        ),
        (
            {**MOMENTUM, "params": {**MOMENTUM["params"], "max_position": "1.5"}},
            ["body", "params", "max_position"],
        ),
        ({**MOMENTUM, "params": {"lookbak": 3}}, ["body", "params", "lookbak"]),
        ({**MOMENTUM, "params": {"top_n": "3"}}, ["body", "params", "top_n"]),
        ({**MOMENTUM, "name": ""}, ["body", "name"]),
        ({**MOMENTUM, "surprise": 1}, ["body", "surprise"]),
    ],
)
async def test_a_bad_body_is_a_422_naming_the_field(
    body: dict[str, Any], location: list[str]
) -> None:
    store = FakeStore()
    async with client_for(fake_app(store)) as http:
        response = await http.post(STRATEGIES, json=body, headers=as_role(Role.QUANT))
        assert location in error_locations(response)
        assert store.strategies == {}


async def test_put_replaces_name_kind_and_params() -> None:
    async with client_for(fake_app(FakeStore())) as http:
        quant = as_role(Role.QUANT)
        created = (await http.post(STRATEGIES, json=MOMENTUM, headers=quant)).json()
        edited = await http.put(
            f"{STRATEGIES}/{created['id']}",
            json={"name": "Now crossover", "kind": "ma_crossover", "params": {"fast": 3}},
            headers=quant,
        )
        assert edited.status_code == 200, edited.text
        body = edited.json()
        assert body["id"] == created["id"] and body["owner_id"] == created["owner_id"]
        assert body["kind"] == "ma_crossover" and body["params"]["fast"] == 3
        reloaded = (await http.get(f"{STRATEGIES}/{created['id']}", headers=quant)).json()
        assert reloaded == body

        bad = await http.put(
            f"{STRATEGIES}/{created['id']}",
            json={**MOMENTUM, "params": {"lookback": -1}},
            headers=quant,
        )
        assert ["body", "params", "lookback"] in error_locations(bad)


async def test_unknown_strategies_are_404() -> None:
    async with client_for(fake_app(FakeStore())) as http:
        quant = as_role(Role.QUANT)
        missing = f"{STRATEGIES}/{uuid.uuid4()}"
        got = await http.get(missing, headers=quant)
        assert got.status_code == 404
        assert got.json()["type"] == "urn:quantsim:problem:not-found"
        assert (await http.put(missing, json=MOMENTUM, headers=quant)).status_code == 404
        assert (await http.get(f"{STRATEGIES}/not-a-uuid", headers=quant)).status_code == 422


async def test_a_strategy_whose_portfolio_has_run_is_not_edited() -> None:
    store = FakeStore()
    async with client_for(fake_app(store)) as http:
        quant = as_role(Role.QUANT)
        created = (await http.post(STRATEGIES, json=MOMENTUM, headers=quant)).json()
        portfolio = await http.post(
            f"{API}/portfolios",
            json={
                "name": "Ran",
                "strategy_id": created["id"],
                "initial_capital": "1000",
                "replay_environment_id": str(uuid.uuid4()),
            },
            headers=quant,
        )
        assert portfolio.status_code == 201, portfolio.text
        store.add_log(uuid.UUID(portfolio.json()["id"]), 3)
        refused = await http.put(f"{STRATEGIES}/{created['id']}", json=MOMENTUM, headers=quant)
        assert refused.status_code == 409
        assert refused.json()["type"] == "urn:quantsim:problem:strategy-in-use"
