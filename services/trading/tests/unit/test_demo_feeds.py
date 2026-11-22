"""The DEV stand-in for Lane B's feeds (qs_trading.demo.feeds): it serves the recorded
contract fixtures the way the contract describes, a run over it equals the same run over
the files (J2), and demo environments keep precedence over a configured feed."""

import json
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr, ValidationError

from qs_template.service_client import StaticServiceToken
from qs_trading.adapters.feed_client import service_client_feed
from qs_trading.adapters.file_environment import FileEnvironment
from qs_trading.adapters.http_environment import ReplayFeed, SimulationPathFeed
from qs_trading.demo.feeds import (
    FILE_COPY_ID,
    REPLAY_FILE,
    REPLAY_ID,
    RUN_FILE,
    RUN_ID,
    demo_feeds_app,
)
from qs_trading.engine.core import RunSpec
from qs_trading.engine.runner import MemorySink, RunResult, run_portfolio
from qs_trading.jobs import BUNDLED_DEMO_ENVIRONMENTS, environment_factory
from qs_trading.ports.market_environment import EnvironmentRef, MarketEnvironment
from qs_trading.settings import TradingSettings

CONTRACTS = Path(__file__).resolve().parents[1] / "fixtures/contracts"

BASE = "http://trading.test/demo-feeds"
TOKEN = "dev-service-token-0123456789abcdef0123"
FILE_COPY = BUNDLED_DEMO_ENVIRONMENTS / f"{FILE_COPY_ID}.json"


def _transport() -> httpx.ASGITransport:
    # Mounted the way build_app mounts it
    app = FastAPI()
    app.mount("/demo-feeds", demo_feeds_app())
    return httpx.ASGITransport(app=app)


async def _no_wait(seconds: float) -> None:
    return None


def _client() -> Any:
    tokens = StaticServiceToken(SecretStr(TOKEN), environment="dev")
    return service_client_feed(BASE, tokens, transport=_transport(), sleep=_no_wait)


def _settings(environment: str, **values: Any) -> TradingSettings:
    return TradingSettings(
        environment=environment,
        database_url=SecretStr("postgresql+asyncpg://unused:unused@127.0.0.1:1/unused"),
        redis_url=SecretStr("redis://127.0.0.1:1/0"),
        **values,
    )


def _spec(ref: EnvironmentRef) -> RunSpec:
    return RunSpec(
        portfolio_id=uuid.UUID("0a170000-0000-4000-8000-000000000003"),
        strategy_kind="buy_and_hold",
        strategy_params={},
        initial_capital=Decimal("100000"),
        cost_model={"fixed": "1.00", "per_share": "0", "pct": "0.0005"},
        slippage_model={"kind": "fixed_bps", "bps": "10"},
        environment=ref,
    )


async def _run(environment: MarketEnvironment, ref: EnvironmentRef) -> tuple[RunResult, MemorySink]:
    sink = MemorySink()
    return await run_portfolio(_spec(ref), environment, sink), sink


def _payloads(sink: MemorySink) -> list[tuple[str, str]]:
    """The events without what names the environment (the spec, and each tick's env id)."""

    def scrub(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                k: scrub(v)
                for k, v in value.items()
                if k not in {"spec", "environment", "env_id", "portfolio_id"}
            }
        if isinstance(value, list):
            return [scrub(v) for v in value]
        return value

    return [
        (str(event.type), json.dumps(scrub(event.payload_json), sort_keys=True, default=str))
        for event in sink.events
    ]


def test_the_bundled_feeds_are_the_contract_fixtures() -> None:
    assert REPLAY_FILE.read_bytes() == (CONTRACTS / "replay_ticks_2020.json").read_bytes()
    assert RUN_FILE.read_bytes() == (CONTRACTS / "synthetic_ticks.json").read_bytes()


def test_the_file_copy_differs_from_the_replay_only_in_its_id_and_name() -> None:
    replay = json.loads(REPLAY_FILE.read_bytes())
    copy = json.loads(FILE_COPY.read_bytes())
    assert copy["environment"]["id"] == FILE_COPY_ID
    for key in ("id", "name"):
        replay["environment"].pop(key)
        copy["environment"].pop(key)
    assert copy["environment"] == replay["environment"]
    strip = [{k: v for k, v in item.items() if k != "env_id"} for item in replay["items"]]
    assert [{k: v for k, v in item.items() if k != "env_id"} for item in copy["items"]] == strip
    assert {item["env_id"] for item in copy["items"]} == {FILE_COPY_ID}


async def test_j2_a_replay_over_the_stand_in_equals_the_same_replay_from_its_file() -> None:
    ref = EnvironmentRef("replay", REPLAY_ID)
    over_http, http_log = await _run(ReplayFeed(_client(), REPLAY_ID), ref)
    over_file, file_log = await _run(FileEnvironment(REPLAY_FILE), ref)
    assert over_http.final_hash == over_file.final_hash
    assert [e.hash for e in http_log.events] == [e.hash for e in file_log.events]
    assert over_http.sessions == 253


async def test_j2_the_file_copy_gives_the_same_run_under_its_own_id() -> None:
    """What the DEV live check compares: the hashes differ only because the spec names
    another environment; the fingerprint, value, fills and every event otherwise match."""
    over_http, http_log = await _run(
        ReplayFeed(_client(), REPLAY_ID), EnvironmentRef("replay", REPLAY_ID)
    )
    copy_ref = EnvironmentRef("replay", FILE_COPY_ID)
    over_copy, copy_log = await _run(FileEnvironment(FILE_COPY), copy_ref)
    assert over_copy.source_fingerprint == over_http.source_fingerprint
    assert over_copy.final_value == over_http.final_value
    assert over_copy.final_seq == over_http.final_seq
    assert _payloads(copy_log) == _payloads(http_log)
    assert over_copy.final_hash != over_http.final_hash


async def test_j2_a_synthetic_path_over_the_stand_in_equals_its_file() -> None:
    ref = EnvironmentRef("simulation", RUN_ID, 2)
    over_http, _ = await _run(SimulationPathFeed(_client(), RUN_ID, 2), ref)
    over_file, _ = await _run(FileEnvironment(RUN_FILE, path_index=2), ref)
    assert over_http.final_hash == over_file.final_hash
    assert over_http.source_fingerprint == over_file.source_fingerprint


async def _get(path: str, **headers: str) -> httpx.Response:
    async with httpx.AsyncClient(transport=_transport(), base_url=BASE) as client:
        return await client.get(path, headers=headers)


async def test_without_a_token_the_stand_in_answers_401() -> None:
    response = await _get(f"/api/market/environments/{REPLAY_ID}")
    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/problem+json")


@pytest.mark.parametrize(
    ("path", "status"),
    [
        (f"/api/market/environments/{uuid.UUID(int=0)}", 404),
        (f"/api/simulation/runs/{uuid.UUID(int=0)}/ticks?path=0", 404),
        (f"/api/market/environments/{REPLAY_ID}/ticks?limit=2001", 422),
        (f"/api/market/environments/{REPLAY_ID}/ticks?after_seq=x", 422),
        (f"/api/simulation/runs/{RUN_ID}/ticks", 422),
        (f"/api/simulation/runs/{RUN_ID}/ticks?path=9", 422),
    ],
)
async def test_bad_requests_get_a_problem(path: str, status: int) -> None:
    response = await _get(path, Authorization=f"Bearer {TOKEN}")
    assert response.status_code == status
    assert response.json()["status"] == status


async def test_pages_carry_the_fingerprint_and_the_next_cursor() -> None:
    response = await _get(
        f"/api/market/environments/{REPLAY_ID}/ticks?after_seq=0&limit=2",
        Authorization=f"Bearer {TOKEN}",
    )
    body = response.json()
    assert response.headers["X-Source-Fingerprint"] == body["items"][0]["source_fingerprint"]
    assert [item["seq"] for item in body["items"]] == [1, 2]
    assert body["next_after_seq"] == 2


def test_a_demo_environment_is_read_from_its_file_even_with_a_feed_configured() -> None:
    settings = _settings(
        "dev",
        trading_demo_environments="bundled",
        trading_market_url=BASE,
        service_token=SecretStr(TOKEN),
    )
    factory = environment_factory(settings, market=_client())
    assert isinstance(factory(EnvironmentRef("replay", FILE_COPY_ID)), FileEnvironment)
    assert isinstance(factory(EnvironmentRef("replay", REPLAY_ID)), ReplayFeed)


@pytest.mark.parametrize("environment", ["test", "acc", "prod"])
def test_the_stand_in_is_refused_outside_local_and_dev(environment: str) -> None:
    with pytest.raises(ValidationError, match="QS_TRADING_DEMO_FEEDS is for local and dev only"):
        _settings(environment, trading_demo_feeds=True)
