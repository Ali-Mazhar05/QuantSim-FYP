"""Rebuild, verification and point-in-time state of one portfolio (task A15).

Each function runs in the caller's transaction (the API's request session, or the CLI's
:meth:`~qs_template.Database.transaction`).

- :func:`rebuild_portfolio` (A-FR-11, ``POST /portfolios/{id}/rebuild`` and
  ``python -m qs_trading rebuild``): locks the portfolio's log against appends, verifies
  its hash chain, folds it again from ``seq = 1`` and compares the result with the stored
  projections row for row. It reports ``identical`` or ``differs`` (naming the tables and
  rows), plus the final ``seq`` and hash. With ``apply=True`` a differing portfolio has its
  projections replaced by the rebuilt rows in the same transaction.
- :func:`verify_portfolio` (A-FR-10, ``python -m qs_trading verify``): the chain report.
- :func:`state_as_of` (A-FR-15, ``GET /portfolios/{id}/state?as_of_seq=``): the state
  after the event at ``seq``, folded from the verified log up to it.

``portfolio_metrics`` is computed per run from the value series (A16), not folded from
events, so the rebuild leaves it alone; the outbox is a delivery queue, not a projection.
"""

import uuid
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from qs_trading.engine.store import PortfolioNotFound
from qs_trading.models import portfolio, portfolio_state_current
from qs_trading.projections.compare import TableDifference, compare_projections
from qs_trading.projections.fold import (
    PortfolioSnapshot,
    ProjectedEvent,
    Projection,
    project_log,
    snapshot_at,
)
from qs_trading.projections.persist import (
    clear_projections,
    lock_log,
    read_log,
    read_projection,
    write_rows,
    write_state,
)
from qs_trading.projections.verify import ChainReport, StoredEvent, verify_chain

__all__ = [
    "ChainBroken",
    "PortfolioNotFound",
    "RebuildResult",
    "rebuild_portfolio",
    "rebuild_projection",
    "state_as_of",
    "verify_portfolio",
]


class ChainBroken(RuntimeError):
    """The stored log fails verification, so nothing can be folded from it."""

    def __init__(self, report: ChainReport) -> None:
        super().__init__(
            f"the log of portfolio {report.portfolio_id} breaks at seq {report.broken_seq}:"
            f" {report.reason}"
        )
        self.report = report


@dataclass(frozen=True, slots=True)
class RebuildResult:
    """``identical`` when the stored projections equal the log folded again, row for row;
    ``differs`` otherwise, with every differing table. ``applied`` says the rebuilt rows
    replaced the stored ones."""

    portfolio_id: uuid.UUID
    status: Literal["identical", "differs"]
    events: int
    final_seq: int
    final_hash: str | None
    differences: tuple[TableDifference, ...] = ()
    applied: bool = False

    @property
    def identical(self) -> bool:
        return self.status == "identical"

    def to_json(self) -> dict[str, Any]:
        return {
            "portfolio_id": str(self.portfolio_id),
            "status": self.status,
            "events": self.events,
            "final_seq": self.final_seq,
            "final_hash": self.final_hash,
            "differences": [difference.to_json() for difference in self.differences],
            "applied": self.applied,
        }


async def _require_portfolio(session: AsyncSession, portfolio_id: uuid.UUID) -> None:
    found = await session.scalar(select(portfolio.c.id).where(portfolio.c.id == portfolio_id))
    if found is None:
        raise PortfolioNotFound(str(portfolio_id))


def _verified(portfolio_id: uuid.UUID, log: list[StoredEvent]) -> list[ProjectedEvent]:
    report = verify_chain(portfolio_id, log)
    if not report.valid:
        raise ChainBroken(report)
    return [
        ProjectedEvent.from_stored(
            seq=event.seq,
            prev_hash=event.prev_hash,
            hash=event.hash,
            event_type=event.type,
            version=event.version,
            payload=event.payload,
        )
        for event in log
    ]


def rebuild_projection(portfolio_id: uuid.UUID, events: list[ProjectedEvent]) -> Projection:
    """The projections of a whole log, folded from ``seq = 1``."""
    ledger, rows = project_log(portfolio_id, events)
    return Projection.from_rows(rows, ledger.state_row())


async def verify_portfolio(session: AsyncSession, portfolio_id: uuid.UUID) -> ChainReport:
    """Verifies the stored hash chain of the portfolio's log."""
    await _require_portfolio(session, portfolio_id)
    return verify_chain(portfolio_id, await read_log(session, portfolio_id))


async def rebuild_portfolio(
    session: AsyncSession, portfolio_id: uuid.UUID, *, apply: bool = False
) -> RebuildResult:
    """Rebuilds the portfolio's projections from its log and compares them with the
    stored ones; ``apply`` replaces differing stored rows. Raises :class:`ChainBroken` when
    the log fails verification (nothing is written then)."""
    await _require_portfolio(session, portfolio_id)
    await lock_log(session, portfolio_id)
    log = await read_log(session, portfolio_id)
    events = _verified(portfolio_id, log)
    rebuilt = rebuild_projection(portfolio_id, events)
    differences = compare_projections(await read_projection(session, portfolio_id), rebuilt)
    applied = False
    if apply and differences:
        _, rows = project_log(portfolio_id, events)
        await clear_projections(session, portfolio_id)
        await write_rows(session, portfolio_id, rows)
        if rebuilt.state is not None:
            await write_state(session, rebuilt.state)
        else:
            await session.execute(
                delete(portfolio_state_current).where(
                    portfolio_state_current.c.portfolio_id == portfolio_id
                )
            )
        applied = True
    final = log[-1] if log else None
    return RebuildResult(
        portfolio_id=portfolio_id,
        status="differs" if differences else "identical",
        events=len(log),
        final_seq=0 if final is None else final.seq,
        final_hash=None if final is None else final.hash,
        differences=differences,
        applied=applied,
    )


async def state_as_of(
    session: AsyncSession, portfolio_id: uuid.UUID, seq: int
) -> PortfolioSnapshot:
    """The portfolio's state right after the event at ``seq``. Raises ``LookupError``
    (:class:`PortfolioNotFound` for an unknown portfolio) when there is no such event, and
    :class:`ChainBroken` when the log up to ``seq`` fails verification."""
    await _require_portfolio(session, portfolio_id)
    log = await read_log(session, portfolio_id, up_to_seq=seq)
    return snapshot_at(portfolio_id, _verified(portfolio_id, log), seq)
