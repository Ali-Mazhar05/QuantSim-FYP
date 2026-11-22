"""The figures a portfolio's run metrics are computed from (task A16), read from the
projections.

Shared by the trading API (``GET /portfolios/{id}/metrics``) and the engine store, which
stores the metrics in the transaction that completes a run. It lives here, not in
:mod:`qs_trading.api_store`, because the API store builds on the engine job, which builds
on the engine store.
"""

import uuid
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from qs_trading.metrics import RunFigures
from qs_trading.models import fill, portfolio, portfolio_state_current, portfolio_value

__all__ = ["load_run_figures"]


async def load_run_figures(session: AsyncSession, portfolio_id: uuid.UUID) -> RunFigures:
    """Initial capital, the value series, fill count, costs and notional, and the log head.

    ``LookupError`` for an unknown portfolio. Reads the uncommitted rows of ``session``,
    so the engine can call it inside the transaction that commits a run's last session.
    """
    capital = await session.scalar(
        select(portfolio.c.initial_capital).where(portfolio.c.id == portfolio_id)
    )
    if capital is None:
        raise LookupError(f"no portfolio has id {portfolio_id}")
    f = fill.c
    trades, costs, notional = (
        await session.execute(
            select(
                func.count(),
                func.coalesce(func.sum(f.cost_total), 0),
                func.coalesce(func.sum(f.fill_price * f.quantity), 0),
            ).where(f.portfolio_id == portfolio_id)
        )
    ).one()
    v = portfolio_value.c
    values = await session.scalars(
        select(v.value).where(v.portfolio_id == portfolio_id).order_by(v.session, v.seq)
    )
    s = portfolio_state_current.c
    head = (
        await session.execute(select(s.last_seq, s.last_hash).where(s.portfolio_id == portfolio_id))
    ).first()
    return RunFigures(
        portfolio_id=portfolio_id,
        initial_capital=capital,
        values=tuple(values),
        trades=int(trades),
        total_costs=Decimal(costs),
        traded_notional=Decimal(notional),
        final_seq=0 if head is None else int(head.last_seq),
        final_hash=None if head is None else head.last_hash,
    )
