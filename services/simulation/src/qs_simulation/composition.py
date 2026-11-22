"""How the service's pieces are put together (B15, B16): the dependencies, and the job handlers
built from them. The API process (embedded workers) and the standalone worker both use this, so a
job is run by the same code wherever it is claimed.

The price and correlation sources read the market service through the service client (K3), at
``QS_SIMULATION_MARKET_URL``. Without that URL there is nothing to read from, so
:func:`default_dependencies` returns no sources, the routes that need them answer 503 and their
jobs are not registered.
"""

from collections.abc import Mapping
from dataclasses import dataclass

import httpx

from qs_simulation.adapters.calibrators import QuantCalibrator
from qs_simulation.adapters.correlation_sources import MarketCorrelationSource
from qs_simulation.adapters.market_client import JsonPoster
from qs_simulation.adapters.price_sources import MarketPriceSource
from qs_simulation.adapters.risk import default_risk
from qs_simulation.calibrations import KIND as CALIBRATE
from qs_simulation.calibrations import make_handler as make_calibration_handler
from qs_simulation.jobs import HANDLERS
from qs_simulation.ports import Calibrator, CorrelationSource, PriceWindowSource, RiskCalculator
from qs_simulation.runs import KIND as MONTE_CARLO
from qs_simulation.runs import make_handler as make_run_handler
from qs_simulation.runs import shard_workers
from qs_simulation.settings import SimulationSettings
from qs_template import Database
from qs_template.jobs import Handler
from qs_template.service_client import ServiceClient, service_tokens_from_settings


@dataclass(frozen=True)
class Dependencies:
    price_source: PriceWindowSource | None
    correlation_source: CorrelationSource | None
    calibrator: Calibrator
    risk: RiskCalculator

    @property
    def can_calibrate(self) -> bool:
        return self.price_source is not None

    @property
    def can_run(self) -> bool:
        return self.price_source is not None and self.correlation_source is not None


def market_sources(
    settings: SimulationSettings, *, transport: httpx.AsyncBaseTransport | None = None
) -> tuple[PriceWindowSource, CorrelationSource]:
    """The market's prices and correlations through one service client: service token, timeouts,
    retries and a circuit breaker (K3). ``transport`` lets a test stand in for the network."""
    client = ServiceClient(
        settings.simulation_market_url,
        caller="simulation",
        tokens=service_tokens_from_settings(settings),
        transport=transport,
    )
    prices = MarketPriceSource(client)
    return prices, MarketCorrelationSource(JsonPoster(client), prices)


def default_dependencies(settings: SimulationSettings) -> Dependencies:
    """What this deployment runs with: the fits and risk code that are installed, and the market
    sources when ``QS_SIMULATION_MARKET_URL`` is set."""
    prices, correlations = (
        market_sources(settings) if settings.simulation_market_url else (None, None)
    )
    return Dependencies(
        price_source=prices,
        correlation_source=correlations,
        calibrator=QuantCalibrator(),
        risk=default_risk(),
    )


def build_handlers(
    settings: SimulationSettings, database: Database, deps: Dependencies
) -> Mapping[str, Handler]:
    """The handlers a worker can run: those whose dependencies exist."""
    handlers: dict[str, Handler] = dict(HANDLERS)
    if deps.price_source is not None:
        handlers[CALIBRATE] = make_calibration_handler(
            database=database, source=deps.price_source, calibrator=deps.calibrator
        )
        if deps.correlation_source is not None:
            handlers[MONTE_CARLO] = make_run_handler(
                database=database,
                prices=deps.price_source,
                correlations=deps.correlation_source,
                risk=deps.risk,
                workers=shard_workers(settings.shard_workers),
                max_attempts=settings.job_max_attempts,
            )
    return handlers
