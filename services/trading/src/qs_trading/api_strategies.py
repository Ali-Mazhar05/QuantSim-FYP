"""Strategy routes, under ``/api/trading`` (task A16, A-FR-01).

Signed-in users (any role):  GET /strategies, GET /strategies/{id}
Quants and admins (``create_strategies``):  POST /strategies
The strategy's owner, or an admin:  PUT /strategies/{id} (another quant gets 403)

A strategy is a built-in ``kind`` plus its ``params`` (ADR 05). The params are checked
against the kind's parameter model and stored in its canonical JSON (defaults filled in,
decimals as strings); an unknown kind or a bad parameter is a 422 whose error location
names the field. A strategy whose portfolios have already written a log is not edited
(409): the log must stay reproducible from the stored spec (A-FR-12, A-FR-13).
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, status
from pydantic import ValidationError

from qs_template import ServiceError
from qs_template.auth import Authenticator, Capability, Principal, Role
from qs_trading.api_store import StoreDependency, TradingStore
from qs_trading.domain.strategies import KINDS, validate_params
from qs_trading.schemas import (
    StrategyIn,
    StrategyOut,
    forbidden,
    not_found,
    validation_problem,
)

STRATEGY_NOT_FOUND = not_found("Strategy")


def may_edit(actor: Principal, owner_id: uuid.UUID) -> bool:
    """Whether ``actor`` may change a strategy owned by ``owner_id``: its owner or an
    admin."""
    return actor.role == Role.ADMIN or actor.user_id == owner_id


def canonical_params(body: StrategyIn) -> dict[str, Any]:
    """The params of ``body`` as stored, or a 422 naming the wrong field."""
    if body.kind not in KINDS:
        raise validation_problem(
            [
                {
                    "location": ["body", "kind"],
                    "message": f"unknown strategy kind; expected one of {', '.join(KINDS)}",
                    "type": "unknown_kind",
                }
            ]
        )
    try:
        params = validate_params(body.kind, body.params)
    except ValidationError as exc:
        raise validation_problem(
            [
                {
                    "location": ["body", "params", *e["loc"]],
                    "message": e["msg"],
                    "type": e["type"],
                }
                for e in exc.errors()
            ]
        ) from None
    stored: dict[str, Any] = params.model_dump(mode="json")
    return stored


def build_strategy_routers(*, auth: Authenticator, store: StoreDependency) -> list[APIRouter]:
    router = APIRouter(prefix="/strategies", tags=["strategies"])

    Reader = Annotated[Principal, Depends(auth.principal)]
    Writer = Annotated[Principal, Depends(auth.require_capability(Capability.CREATE_STRATEGIES))]
    Store = Annotated[TradingStore, Depends(store)]

    @router.get("", responses={401: {}})
    async def list_strategies(_: Reader, store: Store) -> list[StrategyOut]:
        return await store.list_strategies()

    @router.get("/{strategy_id}", responses={401: {}, 404: {}})
    async def get_strategy(strategy_id: uuid.UUID, _: Reader, store: Store) -> StrategyOut:
        found = await store.get_strategy(strategy_id)
        if found is None:
            raise STRATEGY_NOT_FOUND
        return found

    @router.post("", status_code=status.HTTP_201_CREATED, responses={401: {}, 403: {}, 422: {}})
    async def create_strategy(body: StrategyIn, actor: Writer, store: Store) -> StrategyOut:
        params = canonical_params(body)
        return await store.create_strategy(
            name=body.name, kind=body.kind, params=params, owner_id=actor.user_id
        )

    @router.put("/{strategy_id}", responses={401: {}, 403: {}, 404: {}, 409: {}, 422: {}})
    async def replace_strategy(
        strategy_id: uuid.UUID, body: StrategyIn, actor: Writer, store: Store
    ) -> StrategyOut:
        current = await store.get_strategy(strategy_id)
        if current is None:
            raise STRATEGY_NOT_FOUND
        if not may_edit(actor, current.owner_id):
            raise forbidden("Only the strategy's owner or an admin may change it.")
        params = canonical_params(body)
        if await store.strategy_has_run(strategy_id):
            raise ServiceError(
                409,
                "Strategy in use",
                "A portfolio on this strategy has already run; create a new strategy instead.",
                type_="urn:quantsim:problem:strategy-in-use",
            )
        replaced = await store.replace_strategy(
            strategy_id, name=body.name, kind=body.kind, params=params
        )
        if replaced is None:
            raise STRATEGY_NOT_FOUND
        return replaced

    return [router]
