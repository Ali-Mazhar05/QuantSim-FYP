"""Projection, point-in-time, rebuild and metrics routes, under ``/api/trading``
(task A16 part 2: A-FR-11, A-FR-14, A-FR-15).

Signed-in users (any role):
    GET /portfolios/{id}/fills              fills, paged by seq like the event log
    GET /portfolios/{id}/holdings           current positions and cash
    GET /portfolios/{id}/holdings/history   position after every fill, paged by seq
    GET /portfolios/{id}/value-series       valuations, ascending by session
    GET /portfolios/{id}/state?as_of_seq=   state right after an event (the last by default)
    GET /portfolios/{id}/verify             hash-chain report of the log (read-only)
    GET /portfolios/{id}/metrics            run metrics
Admins only:
    POST /portfolios/{id}/rebuild?apply=    rebuild the projections from the log

Every projection is read as stored; ``state`` and ``rebuild`` fold the verified log again.
A log that fails verification or does not fold is a 409
``urn:quantsim:problem:log-broken`` naming ``broken_seq`` and ``reason``; ``verify``
reports it in its body instead (200, ``valid: false``). A ``state`` for a seq the log does
not reach is a 404. ``metrics`` serves trades, costs, sessions and the final value now;
the ratios wait for the shared metrics library (see :mod:`qs_trading.metrics`).
"""

import uuid
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from qs_template import ServiceError
from qs_template.auth import Authenticator, Principal, Role
from qs_trading.api_portfolios import PORTFOLIO_NOT_FOUND
from qs_trading.api_runs import DEFAULT_LIMIT, MAX_LIMIT
from qs_trading.api_store import StoreDependency, TradingStore
from qs_trading.engine.store import PortfolioNotFound
from qs_trading.metrics import MetricsCalculator
from qs_trading.projections.fold import ProjectionError
from qs_trading.projections.rebuild import ChainBroken
from qs_trading.schemas import (
    ChainReportOut,
    FillPage,
    HoldingHistoryPage,
    HoldingsOut,
    MetricsOut,
    RebuildOut,
    StateOut,
    ValuePointOut,
    log_broken,
    money_text,
)

EVENT_NOT_FOUND = ServiceError(
    404,
    "Event not found",
    "The portfolio's trade log has no event at this seq.",
    type_="urn:quantsim:problem:not-found",
)


def _ratio(value: Decimal | None) -> str | None:
    return None if value is None else money_text(value)


def build_projection_routers(
    *, auth: Authenticator, store: StoreDependency, metrics: MetricsCalculator
) -> list[APIRouter]:
    router = APIRouter(prefix="/portfolios/{portfolio_id}", tags=["projections"])

    Reader = Annotated[Principal, Depends(auth.principal)]
    Admin = Annotated[Principal, Depends(auth.require(Role.ADMIN))]
    Store = Annotated[TradingStore, Depends(store)]
    AfterSeq = Annotated[
        int, Query(ge=0, description="next_cursor of the previous page; 0 for the start")
    ]
    Limit = Annotated[int, Query(ge=1, le=MAX_LIMIT)]

    async def known(store: TradingStore, portfolio_id: uuid.UUID) -> None:
        if await store.get_portfolio(portfolio_id) is None:
            raise PORTFOLIO_NOT_FOUND

    @router.get("/fills", responses={401: {}, 404: {}, 422: {}})
    async def list_fills(
        portfolio_id: uuid.UUID,
        _: Reader,
        store: Store,
        after_seq: AfterSeq = 0,
        limit: Limit = DEFAULT_LIMIT,
    ) -> FillPage:
        await known(store, portfolio_id)
        rows = await store.fills(portfolio_id, after_seq, limit + 1)
        page = rows[:limit]
        return FillPage(items=page, next_cursor=page[-1].seq if len(rows) > limit else None)

    @router.get("/holdings", responses={401: {}, 404: {}})
    async def get_holdings(portfolio_id: uuid.UUID, _: Reader, store: Store) -> HoldingsOut:
        await known(store, portfolio_id)
        return await store.holdings(portfolio_id)

    @router.get("/holdings/history", responses={401: {}, 404: {}, 422: {}})
    async def list_holding_history(
        portfolio_id: uuid.UUID,
        _: Reader,
        store: Store,
        after_seq: AfterSeq = 0,
        limit: Limit = DEFAULT_LIMIT,
    ) -> HoldingHistoryPage:
        # A fill changes one symbol, so seq is unique within a portfolio's history
        await known(store, portfolio_id)
        rows = await store.holding_history(portfolio_id, after_seq, limit + 1)
        page = rows[:limit]
        return HoldingHistoryPage(
            items=page, next_cursor=page[-1].seq if len(rows) > limit else None
        )

    @router.get("/value-series", responses={401: {}, 404: {}})
    async def get_value_series(
        portfolio_id: uuid.UUID, _: Reader, store: Store
    ) -> list[ValuePointOut]:
        await known(store, portfolio_id)
        return await store.value_series(portfolio_id)

    @router.get("/state", responses={401: {}, 404: {}, 409: {}, 422: {}})
    async def get_state(
        portfolio_id: uuid.UUID,
        _: Reader,
        store: Store,
        as_of_seq: Annotated[
            int | None, Query(ge=1, description="State after this seq; default the last")
        ] = None,
    ) -> StateOut:
        await known(store, portfolio_id)
        try:
            return await store.state_as_of(portfolio_id, as_of_seq)
        except PortfolioNotFound:
            raise PORTFOLIO_NOT_FOUND from None
        except LookupError:
            raise EVENT_NOT_FOUND from None
        except ChainBroken as broken:
            raise log_broken(broken.report.broken_seq, broken.report.reason) from None
        except ProjectionError as error:
            raise log_broken(error.seq, str(error)) from None

    @router.get("/verify", responses={401: {}, 404: {}})
    async def verify_log(portfolio_id: uuid.UUID, _: Reader, store: Store) -> ChainReportOut:
        await known(store, portfolio_id)
        return await store.verify(portfolio_id)

    @router.post("/rebuild", responses={401: {}, 403: {}, 404: {}, 409: {}, 422: {}})
    async def rebuild_projections(
        portfolio_id: uuid.UUID,
        _: Admin,
        store: Store,
        apply: Annotated[
            bool, Query(description="Replace differing stored rows with the rebuilt ones")
        ] = False,
    ) -> RebuildOut:
        await known(store, portfolio_id)
        try:
            return await store.rebuild(portfolio_id, apply=apply)
        except PortfolioNotFound:
            raise PORTFOLIO_NOT_FOUND from None
        except ChainBroken as broken:
            raise log_broken(broken.report.broken_seq, broken.report.reason) from None
        except ProjectionError as error:
            raise log_broken(error.seq, str(error)) from None

    @router.get("/metrics", responses={401: {}, 404: {}})
    async def get_metrics(portfolio_id: uuid.UUID, _: Reader, store: Store) -> MetricsOut:
        await known(store, portfolio_id)
        figures = await store.run_figures(portfolio_id)
        series = metrics.series_metrics(figures)
        final_value = figures.final_value
        return MetricsOut(
            portfolio_id=portfolio_id,
            final_seq=figures.final_seq,
            final_hash=figures.final_hash,
            sessions=figures.sessions,
            initial_capital=money_text(figures.initial_capital),
            final_value=None if final_value is None else money_text(final_value),
            trades=figures.trades,
            total_costs=money_text(figures.total_costs),
            total_return=_ratio(series.total_return),
            volatility=_ratio(series.volatility),
            sharpe=_ratio(series.sharpe),
            max_drawdown=_ratio(series.max_drawdown),
            turnover=_ratio(series.turnover),
            pending=series.pending(),
        )

    return [router]
