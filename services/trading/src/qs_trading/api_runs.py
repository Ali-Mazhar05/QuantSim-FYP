"""Engine run and trade log routes, under ``/api/trading`` (task A16).

Quants and admins (``create_portfolios``):  POST /portfolios/{id}/runs
Signed-in users (any role):  GET /portfolios/{id}/runs/{job_id},
                             GET /portfolios/{id}/events

A POST only queues the ``engine.run`` job and answers 202 with its id; the worker runs it.
The ``Idempotency-Key`` header makes a retried submit return the same job. Without one a
portfolio has a single run job, so a repeated POST also returns it. A portfolio runs one
job at a time: a new key while another run job of the portfolio is queued or running is
a 409 ``urn:quantsim:problem:run-in-progress`` naming that job in ``job_id``; once it has
succeeded or failed, a new key is accepted.

The event log is paged by keyset on ``seq`` (ADR 01): a page holds the events after
``after_seq``, ascending and gap-free, and ``next_cursor`` is the ``after_seq`` of the
next page (``null`` on the last), so a page costs the same however deep it is.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status

from qs_template.auth import Authenticator, Capability, Principal
from qs_trading.api_portfolios import PORTFOLIO_NOT_FOUND
from qs_trading.api_store import RunInProgress, StoreDependency, TradingStore
from qs_trading.schemas import EventPage, RunAccepted, RunOut, not_found, run_in_progress

RUN_NOT_FOUND = not_found("Run")

DEFAULT_LIMIT = 500
MAX_LIMIT = 2000


def build_run_routers(*, auth: Authenticator, store: StoreDependency) -> list[APIRouter]:
    router = APIRouter(prefix="/portfolios/{portfolio_id}", tags=["runs"])

    Reader = Annotated[Principal, Depends(auth.principal)]
    Runner = Annotated[Principal, Depends(auth.require_capability(Capability.CREATE_PORTFOLIOS))]
    Store = Annotated[TradingStore, Depends(store)]
    IdempotencyKey = Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
            min_length=1,
            max_length=200,
            description="The same key always returns the same job",
        ),
    ]

    async def known(store: TradingStore, portfolio_id: uuid.UUID) -> None:
        if await store.get_portfolio(portfolio_id) is None:
            raise PORTFOLIO_NOT_FOUND

    @router.post(
        "/runs",
        status_code=status.HTTP_202_ACCEPTED,
        responses={401: {}, 403: {}, 404: {}, 409: {}, 422: {}},
    )
    async def start_run(
        portfolio_id: uuid.UUID,
        _: Runner,
        store: Store,
        request: Request,
        response: Response,
        idempotency_key: IdempotencyKey = None,
    ) -> RunAccepted:
        await known(store, portfolio_id)
        try:
            accepted = await store.submit_run(portfolio_id, idempotency_key)
        except RunInProgress as exc:
            raise run_in_progress(exc.job_id) from None
        response.headers["Location"] = request.url_for(
            "get_run", portfolio_id=str(portfolio_id), job_id=str(accepted.job_id)
        ).path
        return accepted

    @router.get("/runs/{job_id}", responses={401: {}, 404: {}})
    async def get_run(
        portfolio_id: uuid.UUID, job_id: uuid.UUID, _: Reader, store: Store
    ) -> RunOut:
        found = await store.get_run(portfolio_id, job_id)
        if found is None:
            raise RUN_NOT_FOUND
        return found

    @router.get("/events", responses={401: {}, 404: {}, 422: {}})
    async def list_events(
        portfolio_id: uuid.UUID,
        _: Reader,
        store: Store,
        after_seq: Annotated[
            int, Query(ge=0, description="next_cursor of the previous page; 0 for the start")
        ] = 0,
        limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
    ) -> EventPage:
        await known(store, portfolio_id)
        rows = await store.events(portfolio_id, after_seq, limit + 1)
        page = rows[:limit]
        return EventPage(items=page, next_cursor=page[-1].seq if len(rows) > limit else None)

    return [router]
