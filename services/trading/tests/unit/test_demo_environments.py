"""Demo environments (DEV only): QS_TRADING_DEMO_ENVIRONMENTS is refused outside LOCAL and
DEV, it picks the worker's environment factory, and the demo shipped in the package runs
end to end, which is what the DEV deploy's live check relies on."""

import json
import uuid
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from qs_trading.engine.core import RunSpec
from qs_trading.engine.runner import MemorySink, run_portfolio
from qs_trading.jobs import BUNDLED_DEMO_ENVIRONMENTS, environment_factory, no_environments
from qs_trading.ports.market_environment import EnvironmentRef, MarketEnvironmentError
from qs_trading.settings import TradingSettings

DEMO_ENV_ID = "5d0c6c1e-7a14-4a14-8a14-000000000001"
DEMO_REF = EnvironmentRef("replay", DEMO_ENV_ID)


def _settings(environment: str, demo: str) -> TradingSettings:
    return TradingSettings(
        environment=environment,
        database_url=SecretStr("postgresql+asyncpg://unused:unused@127.0.0.1:1/unused"),
        redis_url=SecretStr("redis://127.0.0.1:1/0"),
        trading_demo_environments=demo,
    )


@pytest.mark.parametrize("environment", ["local", "dev"])
def test_demo_environments_are_allowed_on_local_and_dev(environment: str) -> None:
    assert _settings(environment, "bundled").trading_demo_environments == "bundled"


@pytest.mark.parametrize("environment", ["test", "acc", "prod"])
def test_demo_environments_are_refused_elsewhere(environment: str) -> None:
    with pytest.raises(ValidationError, match="QS_TRADING_DEMO_ENVIRONMENTS"):
        _settings(environment, "bundled")
    # Off is fine everywhere
    assert _settings(environment, "").trading_demo_environments == ""


def test_the_setting_is_read_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QS_ENVIRONMENT", "prod")
    monkeypatch.setenv("QS_TRADING_DEMO_ENVIRONMENTS", "bundled")
    monkeypatch.setenv("QS_DATABASE_URL", "postgresql+asyncpg://u:p@127.0.0.1:1/d")
    monkeypatch.setenv("QS_REDIS_URL", "redis://127.0.0.1:1/0")
    with pytest.raises(ValidationError, match="local and dev only"):
        TradingSettings()


def test_without_the_setting_no_environment_is_available() -> None:
    factory = environment_factory(_settings("dev", ""))
    assert factory is no_environments
    with pytest.raises(MarketEnvironmentError, match="no market adapter"):
        factory(DEMO_REF)


def test_bundled_opens_the_demo_shipped_in_the_package() -> None:
    assert (BUNDLED_DEMO_ENVIRONMENTS / f"{DEMO_ENV_ID}.json").is_file()
    environment = environment_factory(_settings("dev", "bundled"))(DEMO_REF)
    assert environment.ref == DEMO_REF


def test_a_directory_path_opens_its_fixtures(tmp_path: Path) -> None:
    source = BUNDLED_DEMO_ENVIRONMENTS / f"{DEMO_ENV_ID}.json"
    (tmp_path / source.name).write_bytes(source.read_bytes())
    environment = environment_factory(_settings("local", str(tmp_path)))(DEMO_REF)
    assert environment.ref == DEMO_REF
    with pytest.raises(MarketEnvironmentError):
        environment_factory(_settings("local", str(tmp_path)))(
            EnvironmentRef("replay", str(uuid.UUID(int=7)))
        )


def test_a_missing_directory_stops_the_worker_from_starting(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="not a directory"):
        environment_factory(_settings("dev", str(tmp_path / "missing")))


def test_every_bundled_demo_is_named_by_its_environment_id() -> None:
    files = sorted(BUNDLED_DEMO_ENVIRONMENTS.glob("*.json"))
    assert files
    for path in files:
        assert json.loads(path.read_text())["environment"]["id"] == path.stem


async def test_buy_and_hold_runs_over_the_bundled_demo() -> None:
    """The run the live check submits on DEV: starts, completes, and chains its hashes."""
    spec = RunSpec(
        portfolio_id=uuid.UUID("0a140000-0000-4000-8000-0000000000de"),
        strategy_kind="buy_and_hold",
        strategy_params={},
        initial_capital=Decimal("10000"),
        cost_model={"fixed": "1.00", "per_share": "0.01", "pct": "0.0005"},
        slippage_model={"kind": "fixed_bps", "bps": "5"},
        environment=DEMO_REF,
    )
    sink = MemorySink()
    environment = environment_factory(_settings("dev", "bundled"))(DEMO_REF)
    result = await run_portfolio(spec, environment, sink)
    types = [event.type.value for event in sink.events]
    assert types[0] == "RUN_STARTED" and types[-1] == "RUN_COMPLETED"
    assert [event.seq for event in sink.events] == list(range(1, len(sink.events) + 1))
    for previous, current in zip(sink.events, sink.events[1:], strict=False):
        assert current.prev_hash == previous.hash
    assert result.final_hash == sink.events[-1].hash
