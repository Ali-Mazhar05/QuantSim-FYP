"""Portfolio routes, under ``/api/trading`` (task A16, A-FR-04).

Signed-in users (any role):  GET /portfolios, GET /portfolios/{id}
Quants and admins (``create_portfolios``):  POST /portfolios

A portfolio is bound to exactly one market environment: a replay environment, or one
path of a simulation run. Binding to neither or both is a 422 naming the fields (the
``portfolio_environment_binding`` CHECK refuses it in the database as well). The cost and
slippage models are validated by their domain models and stored in canonical JSON.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from qs_template.auth import Authenticator, Capability, Principal
from qs_trading.api_store import PortfolioValues, StoreDependency, TradingStore
from qs_trading.domain.money import cents
from qs_trading.schemas import PortfolioCreate, PortfolioOut, not_found, validation_problem

PORTFOLIO_NOT_FOUND = not_found("Portfolio")


def portfolio_values(body: PortfolioCreate) -> PortfolioValues:
    """The new row for ``body``, whose binding is already known to be valid."""
    return {
        "name": body.name,
        "strategy_id": body.strategy_id,
        "initial_capital": cents(body.initial_capital),
        "cost_model": body.cost_model.to_json(),
        "slippage_model": body.slippage_model.to_json(),
        "env_type": body.env_type,
        "replay_environment_id": body.replay_environment_id,
        "simulation_run_id": body.simulation_run_id,
        "path_index": body.path_index,
    }


def build_portfolio_routers(*, auth: Authenticator, store: StoreDependency) -> list[APIRouter]:
    router = APIRouter(prefix="/portfolios", tags=["portfolios"])

    Reader = Annotated[Principal, Depends(auth.principal)]
    Writer = Annotated[Principal, Depends(auth.require_capability(Capability.CREATE_PORTFOLIOS))]
    Store = Annotated[TradingStore, Depends(store)]

    @router.get("", responses={401: {}})
    async def list_portfolios(_: Reader, store: Store) -> list[PortfolioOut]:
        return await store.list_portfolios()

    @router.get("/{portfolio_id}", responses={401: {}, 404: {}})
    async def get_portfolio(portfolio_id: uuid.UUID, _: Reader, store: Store) -> PortfolioOut:
        found = await store.get_portfolio(portfolio_id)
        if found is None:
            raise PORTFOLIO_NOT_FOUND
        return found

    @router.post("", status_code=status.HTTP_201_CREATED, responses={401: {}, 403: {}, 422: {}})
    async def create_portfolio(body: PortfolioCreate, actor: Writer, store: Store) -> PortfolioOut:
        if errors := body.binding_errors():
            raise validation_problem(errors)
        if await store.get_strategy(body.strategy_id) is None:
            raise validation_problem(
                [
                    {
                        "location": ["body", "strategy_id"],
                        "message": "no strategy has this id",
                        "type": "unknown_strategy",
                    }
                ]
            )
        return await store.create_portfolio(portfolio_values(body), owner_id=actor.user_id)

    # A16 part 2 (needs the A15 projections and K6 metrics), under this prefix:
    #   GET /{portfolio_id}/fills, /holdings, /value-series   projections, any role
    #   GET /{portfolio_id}/state?as_of_seq=                  point-in-time state, any role
    #   GET /{portfolio_id}/metrics                           per-run metrics, any role
    #   POST /{portfolio_id}/rebuild                          rebuild projections, admin

    return [router]
