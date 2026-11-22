"""Doubles and a small world for the calibration tests (B15): a price source and a calibrator the
test controls, a migrated database and the real app, queue and worker around them."""

import math
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import httpx
import numpy as np
import pytest
from fakeredis import FakeAsyncRedis
from pydantic import SecretStr
from sqlalchemy import text

from qs_simulation.adapters.calibrators import QuantCalibrator
from qs_simulation.calibrations import KIND, make_handler
from qs_simulation.domain.calibration import FitResult, Model, PricePoint, log_returns
from qs_simulation.jobs import job_queue
from qs_simulation.main import build_app
from qs_simulation.ports import (
    Calibrator,
    CalibratorUnavailable,
    InstrumentInfo,
    InstrumentNotFound,
    PriceSourceError,
)
from qs_simulation.settings import SimulationSettings
from qs_template import Database
from qs_template.auth import Authenticator, StaticKeys
from qs_template.jobs import JobQueue, Worker
from qs_template.revocation import RevocationList
from tests.auth_support import API, _jwks

DT = 1 / 252
START = date(2020, 1, 2)
AAPL = uuid.UUID("8d0aba1d-1737-59a8-8b52-846d1791226f")


def make_points(
    n: int, *, seed: int = 1, start: date = START, price: float = 100.0
) -> list[PricePoint]:
    """``n`` consecutive weekdays of a random walk, as adjusted closes."""
    rng = np.random.default_rng(seed)
    closes = price * np.exp(np.cumsum(rng.normal(0.0004, 0.012, size=n)))
    points: list[PricePoint] = []
    day = start
    for close in closes:
        while day.weekday() >= 5:
            day += timedelta(days=1)
        points.append(PricePoint(day, Decimal(f"{close:.10f}"), revision=1))
        day += timedelta(days=1)
    return points


def reference_gbm(points: list[PricePoint]) -> FitResult:
    """The GBM maximum likelihood fit as Lane C's mathematical specification gives it (7.2): the
    stand-in for K5 in these tests, written from the formulas and not from the code under test."""
    r = log_returns(points)
    n = len(r)
    if n < 60:
        return FitResult("gbm", {}, {}, 0.0, 0.0, n, False, "fewer than 60 returns")
    m = float(np.mean(r))
    s2 = float(np.mean((r - m) ** 2))
    if s2 == 0:
        return FitResult("gbm", {}, {}, 0.0, 0.0, n, False, "the returns do not vary")
    sigma = math.sqrt(s2 / DT)
    mu = m / DT + sigma**2 / 2
    loglik = -(n / 2) * math.log(2 * math.pi * s2) - n / 2
    return FitResult(
        "gbm",
        {"mu": mu, "sigma": sigma},
        {"mu": sigma / math.sqrt(n * DT), "sigma": sigma / math.sqrt(2 * n)},
        loglik,
        2 * 2 - 2 * loglik,
        n,
        True,
    )


class ReferenceCalibrator:
    """GBM from the specification; anything scripted for a model wins; other models are unavailable
    (as Merton is until K5 delivers it)."""

    version = "reference-0.1"

    def __init__(self, *, scripted: dict[str, FitResult] | None = None) -> None:
        self.scripted = scripted or {}
        self.calls: list[tuple[str, int]] = []

    def supports(self, model: Model) -> bool:
        return model == "gbm" or model in self.scripted

    def fit(self, model: Model, points: list[PricePoint]) -> FitResult:
        self.calls.append((model, len(points)))
        if model in self.scripted:
            return self.scripted[model]
        if model == "gbm":
            return reference_gbm(points)
        raise CalibratorUnavailable(model)


@dataclass
class ScriptedSource:
    """A price source with a script: prices per instrument, and a number of calls that fail."""

    points: dict[uuid.UUID, list[PricePoint]] = field(default_factory=dict)
    failures: int = 0  # how many calls raise PriceSourceError before it works
    calls: int = 0
    error: Exception | None = None  # raised by every window call when set
    symbols: dict[uuid.UUID, str] = field(default_factory=dict)  # default: AAPL

    def add(self, instrument_id: uuid.UUID, points: list[PricePoint]) -> None:
        self.points[instrument_id] = points

    async def instrument(self, instrument_id: uuid.UUID) -> InstrumentInfo:
        if instrument_id not in self.points:
            raise InstrumentNotFound(str(instrument_id))
        symbol = self.symbols.get(instrument_id, "AAPL")
        name = "Apple Inc." if symbol == "AAPL" else f"{symbol} Inc."
        return InstrumentInfo(instrument_id, symbol, name, "active")

    async def window(self, instrument_id: uuid.UUID, start: date, end: date) -> list[PricePoint]:
        self.calls += 1
        if self.error is not None:
            raise self.error
        if self.failures > 0:
            self.failures -= 1
            raise PriceSourceError("the market service is not answering")
        if instrument_id not in self.points:
            raise InstrumentNotFound(str(instrument_id))
        return [p for p in self.points[instrument_id] if start <= p.session_date <= end]


@dataclass
class World:
    database: Database
    queue: JobQueue
    source: ScriptedSource
    calibrator: Any  # the reference double (tests script it) or the real K5 adapter
    client: httpx.AsyncClient
    worker: Worker

    async def run_jobs(self, limit: int = 20) -> int:
        """Run queued jobs the way a worker would; how many were run."""
        ran = 0
        while ran < limit and await self.worker.run_once():
            ran += 1
        return ran


CLEAR = "TRUNCATE run, scenario, calibration, job, instrument_ref, outbox CASCADE"


@asynccontextmanager
async def build_world(database_url: str, calibrator: Calibrator) -> AsyncIterator[World]:
    settings = SimulationSettings(
        database_url=SecretStr(database_url),
        redis_url=SecretStr("redis://unused"),
        auth_jwks_url="http://127.0.0.1:1/jwks.json",
        content_hash="test-hash",
    )
    database = Database(settings)
    async with database.transaction() as session:
        await session.execute(text(CLEAR))
    source = ScriptedSource()
    app = build_app(
        settings,
        database=database,
        revocations=RevocationList(FakeAsyncRedis()),
        authenticator=Authenticator(settings, jwks=StaticKeys(_jwks())),
        price_source=source,
        calibrator=calibrator,
    )
    queue = job_queue(settings)
    handler = make_handler(database=database, source=source, calibrator=calibrator)
    worker = Worker(database, queue, {KIND: handler}, worker_id="test-worker", poll_seconds=0.01)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://simulation"
    ) as http:
        yield World(database, queue, source, calibrator, http, worker)
    async with database.transaction() as session:
        await session.execute(text(CLEAR))
    await database.close()


@pytest.fixture
async def world(migrated_database_url: str) -> AsyncIterator[World]:
    async with build_world(migrated_database_url, ReferenceCalibrator()) as built:
        yield built


@pytest.fixture
async def k5_world(migrated_database_url: str) -> AsyncIterator[World]:
    """The same world with the real fitting code (K5) in place of the reference."""
    async with build_world(migrated_database_url, QuantCalibrator()) as built:
        yield built


CALIBRATIONS = f"{API}/calibrations"


def request_body(**override: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "instrument_id": str(AAPL),
        "model": "gbm",
        "window_start": "2020-01-01",
        "window_end": "2021-12-31",
    }
    body.update(override)
    return body
