"""Shared pieces of the Trading API tests: signed tokens for every role, an in-memory
store that stands in for trading_db, apps wired either way, and the role matrix every
route is checked against."""

import json
import time
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from jwt.algorithms import RSAAlgorithm
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from qs_template import Database, create_app
from qs_template.auth import Authenticator, Role, StaticKeys
from qs_trading.api import build_routers
from qs_trading.api_store import PortfolioValues, TradingStore
from qs_trading.jobs import engine_run_key
from qs_trading.main import build_app
from qs_trading.schemas import (
    EventOut,
    PortfolioOut,
    RunAccepted,
    RunOut,
    StrategyOut,
    money_text,
)
from qs_trading.settings import TradingSettings

API = "/api/trading"
KEY_ID = "trading-test-key"
_PRIVATE = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_FORGED = rsa.generate_private_key(public_exponent=65537, key_size=2048)
UNREACHABLE_DB = "postgresql+asyncpg://unused:unused@127.0.0.1:1/unused"


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


def as_role(role: Role, *, user_id: uuid.UUID | None = None) -> dict[str, str]:
    return bearer(make_token(role, user_id=user_id))


def make_settings(url: str = UNREACHABLE_DB) -> TradingSettings:
    return TradingSettings(
        database_url=SecretStr(url),
        redis_url=SecretStr("redis://127.0.0.1:1/0"),
        auth_jwks_url="http://platform/jwks",
        content_hash="test-hash",
    )


def authenticator(settings: TradingSettings) -> Authenticator:
    return Authenticator(settings, jwks=StaticKeys(_jwks()))


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass
class FakeStore:
    """trading_db in memory, with the same ordering and idempotency rules."""

    strategies: dict[uuid.UUID, StrategyOut] = field(default_factory=dict)
    portfolios: dict[uuid.UUID, PortfolioOut] = field(default_factory=dict)
    jobs: dict[str, RunOut] = field(default_factory=dict)
    logs: dict[uuid.UUID, list[EventOut]] = field(default_factory=dict)

    async def list_strategies(self) -> list[StrategyOut]:
        return list(reversed(self.strategies.values()))

    async def get_strategy(self, strategy_id: uuid.UUID) -> StrategyOut | None:
        return self.strategies.get(strategy_id)

    async def create_strategy(
        self, *, name: str, kind: str, params: dict[str, Any], owner_id: uuid.UUID
    ) -> StrategyOut:
        now = _now()
        created = StrategyOut(
            id=uuid.uuid4(),
            name=name,
            kind=kind,
            params=params,
            owner_id=owner_id,
            created_at=now,
            updated_at=now,
        )
        self.strategies[created.id] = created
        return created

    async def replace_strategy(
        self, strategy_id: uuid.UUID, *, name: str, kind: str, params: dict[str, Any]
    ) -> StrategyOut | None:
        old = self.strategies.get(strategy_id)
        if old is None:
            return None
        new = old.model_copy(
            update={"name": name, "kind": kind, "params": params, "updated_at": _now()}
        )
        self.strategies[strategy_id] = new
        return new

    async def strategy_has_run(self, strategy_id: uuid.UUID) -> bool:
        return any(
            p.strategy_id == strategy_id and self.logs.get(p.id) for p in self.portfolios.values()
        )

    async def list_portfolios(self) -> list[PortfolioOut]:
        return list(reversed(self.portfolios.values()))

    async def get_portfolio(self, portfolio_id: uuid.UUID) -> PortfolioOut | None:
        return self.portfolios.get(portfolio_id)

    async def create_portfolio(
        self, values: PortfolioValues, *, owner_id: uuid.UUID
    ) -> PortfolioOut:
        chosen = self.strategies[values["strategy_id"]]
        now = _now()
        created = PortfolioOut(
            **{**values, "initial_capital": money_text(values["initial_capital"])},
            id=uuid.uuid4(),
            strategy_name=chosen.name,
            strategy_kind=chosen.kind,
            owner_id=owner_id,
            base_currency="USD",
            source_fingerprint=None,
            created_at=now,
            updated_at=now,
        )
        self.portfolios[created.id] = created
        return created

    async def submit_run(self, portfolio_id: uuid.UUID, idempotency_key: str | None) -> RunAccepted:
        key = engine_run_key(portfolio_id, idempotency_key)
        existing = self.jobs.get(key)
        if existing is None:
            existing = RunOut(
                job_id=uuid.uuid4(),
                portfolio_id=portfolio_id,
                status="queued",
                progress=0.0,
                attempts=0,
                max_attempts=3,
                error=None,
                result=None,
                created_at=_now(),
                started_at=None,
                finished_at=None,
            )
            self.jobs[key] = existing
            created = True
        else:
            created = False
        return RunAccepted(
            job_id=existing.job_id,
            portfolio_id=portfolio_id,
            status=existing.status,
            created=created,
        )

    async def get_run(self, portfolio_id: uuid.UUID, job_id: uuid.UUID) -> RunOut | None:
        for state in self.jobs.values():
            if state.job_id == job_id and state.portfolio_id == portfolio_id:
                return state
        return None

    async def events(self, portfolio_id: uuid.UUID, after_seq: int, limit: int) -> list[EventOut]:
        log = self.logs.get(portfolio_id, [])
        return [e for e in log if e.seq > after_seq][:limit]

    # Seeding helpers for the tests

    def add_log(self, portfolio_id: uuid.UUID, count: int) -> list[EventOut]:
        start = datetime(2024, 1, 2, 21, tzinfo=UTC)
        previous: str | None = None
        log: list[EventOut] = []
        for seq in range(1, count + 1):
            digest = f"{seq:064x}"
            log.append(
                EventOut(
                    seq=seq,
                    type="TICK" if seq > 1 else "RUN_STARTED",
                    version=1,
                    event_time=start + timedelta(days=seq),
                    payload={"close": "100.00000000"},
                    prev_hash=previous,
                    hash=digest,
                )
            )
            previous = digest
        self.logs[portfolio_id] = log
        return log


def fake_app(store: TradingStore, settings: TradingSettings | None = None) -> FastAPI:
    """The service's routes over ``store``; the database is never reached."""
    settings = settings or make_settings()
    database = Database(settings)

    def factory(_: AsyncSession) -> TradingStore:
        return store

    return create_app(
        settings,
        database=database,
        routers=build_routers(auth=authenticator(settings), database=database, store=factory),
    )


def db_app(database: Database, settings: TradingSettings) -> FastAPI:
    """The service exactly as deployed, on ``database``."""
    return build_app(settings, database=database, authenticator=authenticator(settings))


@asynccontextmanager
async def client_for(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://trading"
    ) as http:
        yield http


MOMENTUM: dict[str, Any] = {
    "name": "Momentum 2",
    "kind": "momentum",
    "params": {"lookback": 2, "top_n": 1, "rebalance_every": 2, "max_position": "0.9"},
}


def portfolio_body(strategy_id: str, **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "name": "Replay portfolio",
        "strategy_id": strategy_id,
        "initial_capital": "10000",
        "cost_model": {"fixed": "1.00", "per_share": "0.01", "pct": "0.0005"},
        "slippage_model": {"kind": "volume", "bps": "20"},
        "replay_environment_id": str(uuid.uuid4()),
    }
    body.update(overrides)
    return {k: v for k, v in body.items() if v is not None}


def error_locations(response: httpx.Response) -> list[list[Any]]:
    """The ``location`` of every error in a 422 problem."""
    assert response.status_code == 422, response.text
    assert response.headers["content-type"].startswith("application/problem+json")
    return [e["location"] for e in response.json()["errors"]]


ALL_ROLES = frozenset(Role)
WRITERS = frozenset({Role.QUANT, Role.ADMIN})

# (method, path) -> who may call it. Every route of the service is listed, so a new route
# fails test_every_route_has_a_declared_rule until it is added here.
MATRIX: dict[tuple[str, str], frozenset[Role] | None] = {
    ("GET", "/health"): None,
    ("GET", "/ready"): None,
    ("GET", "/strategies"): ALL_ROLES,
    ("POST", "/strategies"): WRITERS,
    ("GET", "/strategies/{strategy_id}"): ALL_ROLES,
    ("PUT", "/strategies/{strategy_id}"): WRITERS,
    ("GET", "/portfolios"): ALL_ROLES,
    ("POST", "/portfolios"): WRITERS,
    ("GET", "/portfolios/{portfolio_id}"): ALL_ROLES,
    ("POST", "/portfolios/{portfolio_id}/runs"): WRITERS,
    ("GET", "/portfolios/{portfolio_id}/runs/{job_id}"): ALL_ROLES,
    ("GET", "/portfolios/{portfolio_id}/events"): ALL_ROLES,
}


@dataclass(frozen=True)
class Targets:
    """Ids the matrix fills its paths with."""

    strategy_id: str
    portfolio_id: str
    job_id: str


async def seed_targets(http: httpx.AsyncClient) -> Targets:
    quant = as_role(Role.QUANT)
    strategy = await http.post(f"{API}/strategies", json=MOMENTUM, headers=quant)
    assert strategy.status_code == 201, strategy.text
    strategy_id = strategy.json()["id"]
    created = await http.post(f"{API}/portfolios", json=portfolio_body(strategy_id), headers=quant)
    assert created.status_code == 201, created.text
    portfolio_id = created.json()["id"]
    run = await http.post(f"{API}/portfolios/{portfolio_id}/runs", headers=quant)
    assert run.status_code == 202, run.text
    return Targets(strategy_id, portfolio_id, run.json()["job_id"])


async def check_role_matrix(
    http: httpx.AsyncClient, targets: Targets, *, unauthenticated_only: bool = False
) -> None:
    """Every caller on every route: the declared roles get past authorisation, other
    roles get 403 and an anonymous or forged token gets 401."""
    callers: list[tuple[str, dict[str, str]]] = [
        ("anonymous", {}),
        ("forged", bearer(make_token(Role.QUANT, forged=True))),
    ]
    if not unauthenticated_only:
        callers += [(role.value, as_role(role)) for role in Role]
    bodies: dict[tuple[str, str], Callable[[int], dict[str, Any]]] = {
        ("POST", "/strategies"): lambda n: {**MOMENTUM, "name": f"Matrix {n}"},
        ("PUT", "/strategies/{strategy_id}"): lambda n: {**MOMENTUM, "name": f"Edited {n}"},
        ("POST", "/portfolios"): lambda n: portfolio_body(targets.strategy_id, name=f"P {n}"),
    }
    n = 0
    for (method, path), allowed in MATRIX.items():
        if allowed is None:
            continue
        url = API + path.format(
            strategy_id=targets.strategy_id,
            portfolio_id=targets.portfolio_id,
            job_id=targets.job_id,
        )
        for who, headers in callers:
            n += 1
            make_body = bodies.get((method, path))
            response = await http.request(
                method, url, headers=headers, json=make_body(n) if make_body else None
            )
            where = (method, path, who, response.text)
            if who in ("anonymous", "forged"):
                assert response.status_code == 401, where
            elif Role(who) in allowed:
                assert response.status_code in (200, 201, 202), where
            else:
                assert response.status_code == 403, where
                assert response.json()["type"] == "urn:quantsim:problem:forbidden", where
