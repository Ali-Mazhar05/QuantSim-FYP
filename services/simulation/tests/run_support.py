"""Doubles, helpers and a world for the Monte Carlo tests (B16): scripted prices and correlations,
calibrations written straight into the table, and the real app, queue and worker (built through the
composition module, so the wiring is tested too) around them."""

import json
import uuid
import zlib
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

import httpx
import numpy as np
import pytest
from fakeredis import FakeAsyncRedis
from pydantic import SecretStr
from sqlalchemy import text

from qs_simulation.adapters.risk import ReferenceRisk
from qs_simulation.composition import Dependencies, build_handlers
from qs_simulation.jobs import job_queue
from qs_simulation.main import build_app
from qs_simulation.models import calibration, instrument_ref
from qs_simulation.ports import (
    CorrelationMatrix,
    CorrelationUnavailable,
    InstrumentNotFound,
)
from qs_simulation.settings import SimulationSettings
from qs_template import Database
from qs_template.auth import Authenticator, StaticKeys
from qs_template.jobs import JobQueue, Worker
from qs_template.revocation import RevocationList
from tests.auth_support import API, _jwks
from tests.calibration_support import CLEAR, ReferenceCalibrator, ScriptedSource, make_points

RUNS = f"{API}/runs"
GBM = {"mu": 0.1, "sigma": 0.25}
OU = {"kappa": 4.0, "theta": 4.6, "sigma": 0.3}
MERTON = {"mu": 0.1, "sigma": 0.2, "lam": 20.0, "mu_j": -0.02, "sigma_j": 0.05}
PARAMS = {"gbm": GBM, "ou": OU, "merton": MERTON}


@dataclass
class ScriptedCorrelations:
    """A correlation source with a script: one off-diagonal value (or a full matrix), cells that
    are undefined, and calls that fail."""

    rho: float = 0.5
    full: np.ndarray | None = None
    unavailable: tuple[tuple[str, str, str], ...] = ()
    failures: int = 0
    calls: int = 0
    asked: list[tuple[list[uuid.UUID], date, date]] = field(default_factory=list)
    error: Exception | None = None

    async def matrix(
        self, instrument_ids: list[uuid.UUID], start: date, end: date
    ) -> CorrelationMatrix:
        self.calls += 1
        self.asked.append((list(instrument_ids), start, end))
        if self.error is not None:
            raise self.error
        if self.failures > 0:
            self.failures -= 1
            raise CorrelationUnavailable("the market service is not answering")
        n = len(instrument_ids)
        values = self.full if self.full is not None else np.full((n, n), self.rho)
        values = np.array(values, dtype=np.float64)
        np.fill_diagonal(values, 1.0)
        return CorrelationMatrix(tuple(instrument_ids), values, 250, self.unavailable)


@dataclass
class RunWorld:
    database: Database
    queue: JobQueue
    settings: SimulationSettings
    source: ScriptedSource
    correlations: ScriptedCorrelations
    calibrator: ReferenceCalibrator
    risk: ReferenceRisk
    client: httpx.AsyncClient
    worker: Worker

    async def run_jobs(self, limit: int = 20) -> int:
        ran = 0
        while ran < limit and await self.worker.run_once():
            ran += 1
        return ran

    async def instrument(
        self, symbol: str = "AAPL", *, model: str = "gbm", converged: bool = True, n: int = 300
    ) -> tuple[uuid.UUID, uuid.UUID]:
        """A priced instrument and a calibration of it (written straight into the table); returns
        (instrument id, calibration id)."""
        instrument_id = uuid.uuid4()
        points = make_points(n, seed=zlib.crc32(symbol.encode()) % 1000 + 1)
        self.source.add(instrument_id, points)
        calibration_id = uuid.uuid4()
        async with self.database.transaction() as session:
            await session.execute(
                instrument_ref.insert().values(
                    instrument_id=instrument_id, symbol=symbol, name=symbol
                )
            )
            await session.execute(
                calibration.insert().values(
                    id=calibration_id,
                    model=model,
                    instrument_id=instrument_id,
                    window_start=points[0].session_date,
                    window_end=points[-1].session_date,
                    params=PARAMS[model],
                    std_errors={k: 0.01 for k in PARAMS[model]},
                    log_likelihood=Decimal("100.5"),
                    aic=Decimal("-197"),
                    n_obs=n - 1,
                    converged=converged,
                    input_fingerprint="xxh3:" + "0" * 32,
                    qs_quant_version="test",
                    created_by=uuid.uuid4(),
                )
            )
        return instrument_id, calibration_id

    async def basket(
        self, count: int = 3, *, model: str = "gbm"
    ) -> list[tuple[uuid.UUID, uuid.UUID]]:
        symbols = [
            "AAPL",
            "MSFT",
            "NVDA",
            "TSLA",
            "KO",
            "SPY",
            "AMZN",
            "GOOG",
            "META",
            "NFLX",
            "ORCL",
        ]
        return [
            await self.instrument(symbols[i % len(symbols)] + str(i), model=model)
            for i in range(count)
        ]

    async def sql(self, statement: str, **values: Any) -> list[Any]:
        async with self.database.transaction() as session:
            return list((await session.execute(text(statement), values)).all())

    async def events(self, kind: str, run_id: str) -> list[dict[str, Any]]:
        rows = await self.sql(
            "SELECT payload FROM outbox WHERE event_type = :k AND message_key = :r ORDER BY id",
            k=kind,
            r=run_id,
        )
        return [json.loads(r.payload) if isinstance(r.payload, str) else r.payload for r in rows]


def run_body(basket: list[tuple[uuid.UUID, uuid.UUID]], **override: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": "gbm",
        "instruments": [{"instrument_id": str(i), "calibration_id": str(c)} for i, c in basket],
        "n_paths": 200,
        "n_steps": 20,
        "seed": 7,
    }
    body.update(override)
    return body


@pytest.fixture
async def run_world(migrated_database_url: str) -> AsyncIterator[RunWorld]:
    settings = SimulationSettings(
        database_url=SecretStr(migrated_database_url),
        redis_url=SecretStr("redis://unused"),
        auth_jwks_url="http://127.0.0.1:1/jwks.json",
        content_hash="test-hash",
        shard_workers=1,
    )
    database = Database(settings)
    async with database.transaction() as session:
        await session.execute(text(CLEAR))
    source, correlations = ScriptedSource(), ScriptedCorrelations()
    calibrator, risk = ReferenceCalibrator(), ReferenceRisk()
    deps = Dependencies(source, correlations, calibrator, risk)
    app = build_app(
        settings,
        database=database,
        revocations=RevocationList(FakeAsyncRedis()),
        authenticator=Authenticator(settings, jwks=StaticKeys(_jwks())),
        price_source=source,
        correlation_source=correlations,
        calibrator=calibrator,
        risk=risk,
    )
    queue = job_queue(settings)
    worker = Worker(
        database,
        queue,
        build_handlers(settings, database, deps),
        worker_id="test-worker",
        poll_seconds=0.01,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://simulation"
    ) as http:
        yield RunWorld(
            database, queue, settings, source, correlations, calibrator, risk, http, worker
        )
    async with database.transaction() as session:
        await session.execute(text(CLEAR))
    await database.close()


__all__ = [
    "RUNS",
    "InstrumentNotFound",
    "RunWorld",
    "ScriptedCorrelations",
    "run_body",
    "run_world",
]
