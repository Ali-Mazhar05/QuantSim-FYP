"""HTTP API of the Trading service, under ``/api/trading`` (task A16).

Signed-in users (any role):  GET /strategies, GET /strategies/{id}, GET /portfolios,
    GET /portfolios/{id}, GET /portfolios/{id}/runs/{job_id}, GET /portfolios/{id}/events
Quants and admins (``create_strategies``):  POST /strategies, PUT /strategies/{id}
Quants and admins (``create_portfolios``):  POST /portfolios, POST /portfolios/{id}/runs
Projections, state, verify and metrics (any role), rebuild (admins): see
:mod:`qs_trading.api_projections`

Errors are problem details; a bad body or parameter is a 422 whose ``errors`` name the
field. Money is a decimal string. The OpenAPI document is served at
``/api/trading/openapi.json``.
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from qs_template import Database
from qs_template.auth import Authenticator
from qs_template.jobs import JobQueue
from qs_trading.api_portfolios import build_portfolio_routers
from qs_trading.api_projections import build_projection_routers
from qs_trading.api_runs import build_run_routers
from qs_trading.api_store import StoreFactory, TradingStore, sql_store
from qs_trading.api_strategies import build_strategy_routers
from qs_trading.metrics import PENDING, MetricsCalculator
from qs_trading.models import job


def build_routers(
    *,
    auth: Authenticator,
    database: Database,
    queue: JobQueue | None = None,
    store: StoreFactory | None = None,
    metrics: MetricsCalculator = PENDING,
) -> list[APIRouter]:
    """Every router of the service. Add new routers here.

    ``queue`` is the job queue runs are submitted to (the service's ``job`` table with the
    default lease and attempts when omitted). ``store`` replaces the trading_db store, for
    tests that run the routes without a database. ``metrics`` computes the run ratios
    (none until the shared metrics library is wired in)."""
    make_store = store or sql_store(queue or JobQueue(job))

    async def request_store(
        session: Annotated[AsyncSession, Depends(database.session)],
    ) -> TradingStore:
        return make_store(session)

    return [
        *build_strategy_routers(auth=auth, store=request_store),
        *build_portfolio_routers(auth=auth, store=request_store),
        *build_run_routers(auth=auth, store=request_store),
        *build_projection_routers(auth=auth, store=request_store, metrics=metrics),
    ]
