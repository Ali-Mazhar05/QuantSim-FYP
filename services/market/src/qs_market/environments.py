"""Market environments: the market a simulation or a replay runs inside (FR-MKT-008,
FR-MKT-009), shaped exactly like the prototype's Market Environments pages.

An environment names a basket of instruments, a window and a frequency. It is created as
``ready`` when every instrument has at least one clean bar inside the window, otherwise as
``draft``; ``active`` is set later by the simulation or replay that uses it (Iteration 2).
Writes run in the caller's audited transaction, so the trigger records who made the change.
"""

import uuid
from datetime import date
from typing import Any

from sqlalchemy import func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from qs_market.models import bar, instrument, market_environment
from qs_template import ServiceError

NOT_FOUND = ServiceError(
    404,
    "Market environment not found",
    "No market environment has this id.",
    type_="urn:quantsim:problem:not-found",
)


def _invalid_instruments(ids: list[str]) -> ServiceError:
    return ServiceError(
        422,
        "Unknown or retired instruments",
        "Every instrument must exist and be active.",
        type_="urn:quantsim:problem:invalid-instruments",
        extra={"instrument_ids": ids},
    )


class EnvironmentService:
    def __init__(self, session: AsyncSession, *, actor_id: uuid.UUID | None = None) -> None:
        self._session = session
        self._actor = actor_id

    async def list_all(self) -> list[dict[str, Any]]:
        rows = await self._session.execute(
            select(market_environment).order_by(
                market_environment.c.created_at.desc(), market_environment.c.id
            )
        )
        return await self._with_symbols([dict(row._mapping) for row in rows.all()])

    async def get(self, environment_id: uuid.UUID) -> dict[str, Any]:
        row = (
            await self._session.execute(
                select(market_environment).where(market_environment.c.id == environment_id)
            )
        ).first()
        if row is None:
            raise NOT_FOUND
        return (await self._with_symbols([dict(row._mapping)]))[0]

    async def create(
        self,
        *,
        name: str,
        type: str,
        universe: str,
        instrument_ids: list[uuid.UUID],
        start_date: date,
        end_date: date,
        frequency: str,
    ) -> dict[str, Any]:
        if self._actor is None:
            raise RuntimeError("creating an environment needs an acting user")
        unique = list(dict.fromkeys(instrument_ids))
        active = set(
            (
                await self._session.execute(
                    select(instrument.c.id).where(
                        instrument.c.id.in_(unique), instrument.c.status == "active"
                    )
                )
            ).scalars()
        )
        missing = [str(i) for i in unique if i not in active]
        if missing:
            raise _invalid_instruments(missing)
        covered = set(
            (
                await self._session.execute(
                    select(bar.c.instrument_id)
                    .where(
                        bar.c.instrument_id.in_(unique),
                        bar.c.session_date >= start_date,
                        bar.c.session_date <= end_date,
                    )
                    .group_by(bar.c.instrument_id)
                    .having(func.count() > 0)
                )
            ).scalars()
        )
        status = "ready" if covered == set(unique) else "draft"
        new_id = (
            await self._session.execute(
                insert(market_environment)
                .values(
                    name=name,
                    type=type,
                    universe=universe,
                    instrument_ids=[str(i) for i in unique],
                    start_date=start_date,
                    end_date=end_date,
                    frequency=frequency,
                    status=status,
                    created_by=self._actor,
                )
                .returning(market_environment.c.id)
            )
        ).scalar_one()
        return await self.get(new_id)

    async def _with_symbols(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Each environment with its instruments' symbols, in the order they were given."""
        ids = {i for row in rows for i in row["instrument_ids"]}
        symbols: dict[str, str] = {}
        if ids:
            found = await self._session.execute(
                select(instrument.c.id, instrument.c.symbol).where(
                    instrument.c.id.in_([uuid.UUID(i) for i in ids])
                )
            )
            symbols = {str(i): s for i, s in found.all()}
        return [
            {**row, "symbols": [symbols[i] for i in row["instrument_ids"] if i in symbols]}
            for row in rows
        ]
