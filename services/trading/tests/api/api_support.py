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
from decimal import Decimal
from pathlib import Path
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
from qs_trading.adapters.file_environment import FileEnvironment
from qs_trading.api import build_routers
from qs_trading.api_ops import OpsFactory, OpsReader, durations_out
from qs_trading.api_store import (
    ACTIVE_JOB_STATUSES,
    PortfolioValues,
    RunInProgress,
    TradingStore,
    chain_report_out,
    fill_out,
    holding_change_out,
    holdings_out,
    rebuild_out,
    state_out,
    value_out,
)
from qs_trading.engine.core import RunSpec
from qs_trading.engine.runner import MemorySink, run_portfolio
from qs_trading.jobs import engine_run_key
from qs_trading.main import build_app
from qs_trading.metrics import PENDING, MetricsCalculator, RunFigures
from qs_trading.ports.market_environment import EnvironmentRef
from qs_trading.projections import (
    ProjectedEvent,
    Projection,
    StoredEvent,
    compare_projections,
    project_log,
    snapshot_at,
    verify_chain,
)
from qs_trading.projections.rebuild import ChainBroken, RebuildResult, rebuild_projection
from qs_trading.schemas import (
    ChainReportOut,
    EventOut,
    FillOut,
    HoldingChangeOut,
    HoldingsOut,
    JobQueueOut,
    OpsMetricsOut,
    OutboxBacklogOut,
    PortfolioOut,
    RebuildOut,
    RunAccepted,
    RunOut,
    StateOut,
    StrategyOut,
    ValuePointOut,
    money_text,
)
from qs_trading.settings import TradingSettings

API = "/api/trading"
FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/environments/two_symbols_10_sessions.json"
ENV_ID = "5d0c6c1e-7a14-4a14-8a14-000000000001"
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
    # The stored log and the stored projection rows of a portfolio that has run
    stored_logs: dict[uuid.UUID, list[StoredEvent]] = field(default_factory=dict)
    projections: dict[uuid.UUID, Projection] = field(default_factory=dict)

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
            for other in self.jobs.values():
                if other.portfolio_id == portfolio_id and other.status in ACTIVE_JOB_STATUSES:
                    raise RunInProgress(portfolio_id, other.job_id)
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

    async def fills(self, portfolio_id: uuid.UUID, after_seq: int, limit: int) -> list[FillOut]:
        rows = self._projection(portfolio_id).fills
        return [fill_out(rows[seq]) for seq in sorted(rows) if seq > after_seq][:limit]

    async def holdings(self, portfolio_id: uuid.UUID) -> HoldingsOut:
        return holdings_out(portfolio_id, self._projection(portfolio_id).state)

    async def holding_history(
        self, portfolio_id: uuid.UUID, after_seq: int, limit: int
    ) -> list[HoldingChangeOut]:
        rows = self._projection(portfolio_id).holdings
        ordered = [rows[key] for key in sorted(rows) if key[0] > after_seq]
        return [holding_change_out(row) for row in ordered][:limit]

    async def value_series(self, portfolio_id: uuid.UUID) -> list[ValuePointOut]:
        return [value_out(row) for row in self._values(portfolio_id)]

    async def state_as_of(self, portfolio_id: uuid.UUID, seq: int | None) -> StateOut:
        log = self.stored_logs.get(portfolio_id, [])
        if seq is None:
            if not log:
                raise LookupError("no events")
            seq = log[-1].seq
        prefix = [event for event in log if event.seq <= seq]
        return state_out(snapshot_at(portfolio_id, self._verified(portfolio_id, prefix), seq))

    async def rebuild(self, portfolio_id: uuid.UUID, *, apply: bool) -> RebuildOut:
        log = self.stored_logs.get(portfolio_id, [])
        rebuilt = rebuild_projection(portfolio_id, self._verified(portfolio_id, log))
        differences = compare_projections(self._projection(portfolio_id), rebuilt)
        if apply and differences:
            self.projections[portfolio_id] = rebuilt
        return rebuild_out(
            RebuildResult(
                portfolio_id=portfolio_id,
                status="differs" if differences else "identical",
                events=len(log),
                final_seq=log[-1].seq if log else 0,
                final_hash=log[-1].hash if log else None,
                differences=differences,
                applied=apply and bool(differences),
            )
        )

    async def verify(self, portfolio_id: uuid.UUID) -> ChainReportOut:
        return chain_report_out(verify_chain(portfolio_id, self.stored_logs.get(portfolio_id, [])))

    async def run_figures(self, portfolio_id: uuid.UUID) -> RunFigures:
        stored = self._projection(portfolio_id)
        fills = list(stored.fills.values())
        state = stored.state
        return RunFigures(
            portfolio_id=portfolio_id,
            initial_capital=Decimal(self.portfolios[portfolio_id].initial_capital),
            values=tuple(row["value"] for row in self._values(portfolio_id)),
            trades=len(fills),
            total_costs=sum((row["cost_total"] for row in fills), Decimal(0)),
            traded_notional=sum((row["fill_price"] * row["quantity"] for row in fills), Decimal(0)),
            final_seq=0 if state is None else state["last_seq"],
            final_hash=None if state is None else state["last_hash"],
        )

    def _projection(self, portfolio_id: uuid.UUID) -> Projection:
        return self.projections.get(portfolio_id, Projection())

    def _values(self, portfolio_id: uuid.UUID) -> list[dict[str, Any]]:
        rows = self._projection(portfolio_id).values.values()
        return sorted(rows, key=lambda row: (row["session"], row["seq"]))

    @staticmethod
    def _verified(portfolio_id: uuid.UUID, log: list[StoredEvent]) -> list[ProjectedEvent]:
        report = verify_chain(portfolio_id, log)
        if not report.valid:
            raise ChainBroken(report)
        return [
            ProjectedEvent.from_stored(
                seq=e.seq,
                prev_hash=e.prev_hash,
                hash=e.hash,
                event_type=e.type,
                version=e.version,
                payload=e.payload,
            )
            for e in log
        ]

    # Seeding helpers for the tests

    async def add_run(self, portfolio_id: uuid.UUID) -> list[StoredEvent]:
        """Runs the portfolio on the A14 fixture as the worker would, and stores its log
        (payloads through JSON, as JSONB gives them back) and its projections."""
        held = self.portfolios[portfolio_id]
        chosen = self.strategies[held.strategy_id]
        spec = RunSpec(
            portfolio_id=portfolio_id,
            strategy_kind=chosen.kind,
            strategy_params=chosen.params,
            initial_capital=Decimal(held.initial_capital),
            cost_model=held.cost_model,
            slippage_model=held.slippage_model,
            environment=EnvironmentRef("replay", ENV_ID),
        )
        sink = MemorySink()
        await run_portfolio(spec, FileEnvironment(FIXTURE), sink)
        log = [
            StoredEvent(
                portfolio_id=portfolio_id,
                seq=e.seq,
                event_time=e.event_time,
                type=e.type.value,
                version=e.version,
                payload=json.loads(json.dumps(e.payload_json)),
                prev_hash=e.prev_hash,
                hash=e.hash,
            )
            for e in sink.events
        ]
        ledger, rows = project_log(portfolio_id, self._verified(portfolio_id, log))
        self.stored_logs[portfolio_id] = log
        self.projections[portfolio_id] = Projection.from_rows(rows, ledger.state_row())
        self.logs[portfolio_id] = [
            EventOut(
                seq=e.seq,
                type=e.type,
                version=e.version,
                event_time=e.event_time,
                payload=dict(e.payload),
                prev_hash=e.prev_hash,
                hash=e.hash,
            )
            for e in log
        ]
        return log

    def finish_runs(self, portfolio_id: uuid.UUID, status: str = "succeeded") -> None:
        """Ends every queued or running run job of the portfolio, as the worker would."""
        for key, state in self.jobs.items():
            if state.portfolio_id == portfolio_id and state.status in ACTIVE_JOB_STATUSES:
                self.jobs[key] = state.model_copy(
                    update={"status": status, "progress": 1.0, "finished_at": _now()}
                )

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


@dataclass
class FakeOps:
    """Fixed operational figures: an idle queue and an empty outbox."""

    async def ops_metrics(self, recent: int) -> OpsMetricsOut:
        return OpsMetricsOut(
            generated_at=_now(),
            queue=JobQueueOut(
                kind="engine.run",
                queued=0,
                running=0,
                succeeded=0,
                failed=0,
                oldest_queued_seconds=None,
            ),
            durations=durations_out([], recent),
            outbox=OutboxBacklogOut(pending=0, oldest_pending_seconds=None),
        )


def _fake_ops(_: AsyncSession) -> OpsReader:
    return FakeOps()


def fake_app(
    store: TradingStore,
    settings: TradingSettings | None = None,
    metrics: MetricsCalculator = PENDING,
    demo_environments: str = "",
    ops: OpsFactory = _fake_ops,
) -> FastAPI:
    """The service's routes over ``store`` and ``ops``; the database is never reached."""
    settings = settings or make_settings()
    database = Database(settings)

    def factory(_: AsyncSession) -> TradingStore:
        return store

    return create_app(
        settings,
        database=database,
        routers=build_routers(
            auth=authenticator(settings),
            database=database,
            store=factory,
            metrics=metrics,
            demo_environments=demo_environments,
            ops=ops,
        ),
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
ADMINS = frozenset({Role.ADMIN})

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
    ("GET", "/portfolios/{portfolio_id}/fills"): ALL_ROLES,
    ("GET", "/portfolios/{portfolio_id}/holdings"): ALL_ROLES,
    ("GET", "/portfolios/{portfolio_id}/holdings/history"): ALL_ROLES,
    ("GET", "/portfolios/{portfolio_id}/value-series"): ALL_ROLES,
    ("GET", "/portfolios/{portfolio_id}/state"): ALL_ROLES,
    ("GET", "/portfolios/{portfolio_id}/verify"): ALL_ROLES,
    ("GET", "/portfolios/{portfolio_id}/metrics"): ALL_ROLES,
    ("POST", "/portfolios/{portfolio_id}/rebuild"): ADMINS,
    ("GET", "/demo-environments"): ALL_ROLES,
    ("GET", "/ops/metrics"): ADMINS,
}

# The matrix's portfolio has not run, so it has no state to read yet: a not-found problem
# from these routes means the caller got past authorisation
NOT_FOUND_BEFORE_A_RUN = frozenset({("GET", "/portfolios/{portfolio_id}/state")})


@dataclass(frozen=True)
class Targets:
    """Ids the matrix fills its paths with."""

    strategy_id: str
    portfolio_id: str
    job_id: str
    # The quant who created them; each role in the matrix acts as this user, so a route
    # that also checks ownership (PUT /strategies/{id}) is judged on the role alone
    owner_id: uuid.UUID


async def seed_targets(http: httpx.AsyncClient) -> Targets:
    owner_id = uuid.uuid4()
    quant = as_role(Role.QUANT, user_id=owner_id)
    strategy = await http.post(f"{API}/strategies", json=MOMENTUM, headers=quant)
    assert strategy.status_code == 201, strategy.text
    strategy_id = strategy.json()["id"]
    created = await http.post(f"{API}/portfolios", json=portfolio_body(strategy_id), headers=quant)
    assert created.status_code == 201, created.text
    portfolio_id = created.json()["id"]
    run = await http.post(f"{API}/portfolios/{portfolio_id}/runs", headers=quant)
    assert run.status_code == 202, run.text
    return Targets(strategy_id, portfolio_id, run.json()["job_id"], owner_id)


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
        callers += [(role.value, as_role(role, user_id=targets.owner_id)) for role in Role]
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
                if (method, path) in NOT_FOUND_BEFORE_A_RUN:
                    assert response.status_code == 404, where
                    assert response.json()["type"] == "urn:quantsim:problem:not-found", where
                else:
                    assert response.status_code in (200, 201, 202), where
            else:
                assert response.status_code == 403, where
                assert response.json()["type"] == "urn:quantsim:problem:forbidden", where
