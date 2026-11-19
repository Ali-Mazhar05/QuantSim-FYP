"""trading_db reads and writes of the projections (task A15).

:func:`write_rows` is how both the engine store (one session at a time, in the session's
transaction) and the rebuild (the whole log at once) write what
:func:`~qs_trading.projections.fold.fold` returns. :func:`read_projection` reads the stored
rows back in the same shape, so the two can be compared row for row.
"""

import uuid
from typing import Any

from sqlalchemy import delete, func, insert, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from qs_trading.models import (
    fill,
    holding_history,
    order,
    portfolio_state_current,
    portfolio_value,
    trade_event,
)
from qs_trading.projections.fold import Projection, ProjectionRows, Row
from qs_trading.projections.verify import StoredEvent

__all__ = [
    "clear_projections",
    "lock_log",
    "read_log",
    "read_projection",
    "write_rows",
    "write_state",
]

# Columns every projection row carries; ``updated_at`` is bookkeeping, not projection
_ORDER_COLUMNS = tuple(c.name for c in order.columns if c.name != "updated_at")
_STATE_COLUMNS = tuple(c.name for c in portfolio_state_current.columns if c.name != "updated_at")


async def write_rows(session: AsyncSession, portfolio_id: uuid.UUID, rows: ProjectionRows) -> None:
    """Inserts the rows some events add and moves the status of the orders they settle.
    Orders go first, as fills refer to them."""
    if rows.orders:
        await session.execute(insert(order), [dict(row) for row in rows.orders])
    for order_id, status in rows.status_changes:
        await session.execute(
            update(order)
            .where(order.c.portfolio_id == portfolio_id, order.c.order_id == order_id)
            .values(status=status, updated_at=func.now())
        )
    for table, table_rows in (
        (fill, rows.fills),
        (holding_history, rows.holdings),
        (portfolio_value, rows.values),
    ):
        if table_rows:
            await session.execute(insert(table), [dict(row) for row in table_rows])


async def write_state(session: AsyncSession, state: Row) -> None:
    """Writes the ``portfolio_state_current`` row, creating it when there is none."""
    values = {**state, "updated_at": func.now()}
    statement = pg_insert(portfolio_state_current).values(**values)
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=[portfolio_state_current.c.portfolio_id],
            set_={key: statement.excluded[key] for key in values if key != "portfolio_id"},
        )
    )


async def clear_projections(session: AsyncSession, portfolio_id: uuid.UUID) -> None:
    """Deletes a portfolio's projection rows (never its log or its state row)."""
    for table in (fill, holding_history, portfolio_value, order):
        await session.execute(delete(table).where(table.c.portfolio_id == portfolio_id))


async def lock_log(session: AsyncSession, portfolio_id: uuid.UUID) -> Row | None:
    """Locks the portfolio's log against appends for the rest of the transaction and
    returns its state row (``None`` when no session was ever committed). The state row is
    locked first, as the engine store locks it, then the per-portfolio append lock the
    ``trade_event`` trigger takes, so the two never wait on each other in a cycle."""
    row = (
        await session.execute(
            select(*(portfolio_state_current.c[name] for name in _STATE_COLUMNS))
            .where(portfolio_state_current.c.portfolio_id == portfolio_id)
            .with_for_update()
        )
    ).first()
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(CAST(:key AS text), 0))"),
        {"key": f"qs_trade_event:{portfolio_id}"},
    )
    return None if row is None else dict(row._mapping)


async def read_log(
    session: AsyncSession, portfolio_id: uuid.UUID, *, up_to_seq: int | None = None
) -> list[StoredEvent]:
    """The portfolio's ``trade_event`` rows in ``seq`` order, up to ``up_to_seq``."""
    query = select(trade_event).where(trade_event.c.portfolio_id == portfolio_id)
    if up_to_seq is not None:
        query = query.where(trade_event.c.seq <= up_to_seq)
    rows = await session.execute(query.order_by(trade_event.c.seq))
    return [StoredEvent.from_row(row) for row in rows]


async def _rows(session: AsyncSession, table: Any, portfolio_id: uuid.UUID) -> list[Row]:
    columns = _ORDER_COLUMNS if table is order else tuple(c.name for c in table.columns)
    result = await session.execute(
        select(*(table.c[name] for name in columns)).where(table.c.portfolio_id == portfolio_id)
    )
    return [dict(row._mapping) for row in result]


async def read_projection(session: AsyncSession, portfolio_id: uuid.UUID) -> Projection:
    """Every stored projection row of the portfolio."""
    state = (
        await session.execute(
            select(*(portfolio_state_current.c[name] for name in _STATE_COLUMNS)).where(
                portfolio_state_current.c.portfolio_id == portfolio_id
            )
        )
    ).first()
    return Projection(
        orders={row["order_id"]: row for row in await _rows(session, order, portfolio_id)},
        fills={row["seq"]: row for row in await _rows(session, fill, portfolio_id)},
        holdings={
            (row["seq"], row["symbol"]): row
            for row in await _rows(session, holding_history, portfolio_id)
        },
        values={row["seq"]: row for row in await _rows(session, portfolio_value, portfolio_id)},
        state=None if state is None else dict(state._mapping),
    )
