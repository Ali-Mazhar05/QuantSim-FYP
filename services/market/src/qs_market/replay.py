"""Replay of a stored daily environment: the ticks it serves and its activation (B12).

The database side of ``qs_market.feeds``. A window can hold 100,000 bars (40 instruments over
11 years) and a page needs 2,000 ticks, so the window is never pulled into Python: PostgreSQL writes
each bar's canonical line and flags gaps, Python hashes the lines, and only the rows of the page are
fetched as values. Both queries read one snapshot, so a restatement that lands during a request
cannot give a page and a fingerprint from different data. The rules are those of ADR 01 and ADR 08;
the reasons are in docs/decision-log.md.
"""

import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import Select, Text, cast, func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from qs_market import feeds
from qs_market.environments import EnvironmentService
from qs_market.models import bar, environment_activation, instrument, market_environment
from qs_template.errors import ServiceError

NOT_A_REPLAY = "urn:quantsim:problem:not-a-replay-environment"
UNSUPPORTED_FREQUENCY = "urn:quantsim:problem:unsupported-frequency"
NOT_READY = "urn:quantsim:problem:environment-not-ready"
MISSING_ADJUSTED = "urn:quantsim:problem:missing-adjusted-prices"

ADJUSTED = (bar.c.adj_open, bar.c.adj_high, bar.c.adj_low, bar.c.adj_close, bar.c.adj_volume)
# the feed order; the instrument id makes it total
FEED_ORDER = (bar.c.session_date, instrument.c.symbol, bar.c.instrument_id)


def check_replayable(environment: dict[str, Any]) -> None:
    """Only a daily, historical environment whose instruments all have data has a replay feed."""
    if environment["type"] != "historical_replay":
        raise ServiceError(
            422,
            "Not a replay environment",
            "Only a historical environment has a replay feed; a synthetic market is read from "
            "its simulation run.",
            type_=NOT_A_REPLAY,
        )
    if environment["frequency"] != "daily":
        raise ServiceError(
            422,
            "Only daily environments can be replayed",
            f"This environment is {environment['frequency']}; replay needs daily bars.",
            type_=UNSUPPORTED_FREQUENCY,
        )
    if environment["status"] == "draft":
        raise ServiceError(
            422,
            "The environment is not ready",
            "Some instrument has no clean bar in the window yet, so there is nothing complete to "
            "replay; ingest the data, then create or recheck the environment.",
            type_=NOT_READY,
        )


def _missing(missing: dict[str, int]) -> ServiceError:
    error = feeds.MissingAdjustedPrices(missing)
    return ServiceError(
        422,
        "Adjusted prices are missing",
        f"{error}. Raw prices are never substituted for adjusted ones.",
        type_=MISSING_ADJUSTED,
        extra={"missing": missing},
    )


@dataclass(frozen=True)
class Window:
    """What the whole window says, read once per request."""

    fingerprint: str
    total: int  # ticks in the feed
    sessions: dict[date, int]  # session date -> index among the sessions present
    per_session: Counter[date]  # bars on each session, for the missing-session count


class ReplayService:
    def __init__(self, session: AsyncSession, *, actor_id: uuid.UUID | None = None) -> None:
        self._session = session
        self._actor = actor_id

    def _in_window(self, query: Select[Any], environment: dict[str, Any]) -> Select[Any]:
        ids = [uuid.UUID(i) for i in environment["instrument_ids"]]
        return (
            query.join(instrument, instrument.c.id == bar.c.instrument_id)
            .where(
                bar.c.instrument_id.in_(ids),
                bar.c.session_date.between(environment["start_date"], environment["end_date"]),
            )
            .order_by(*FEED_ORDER)
        )

    async def window(self, environment: dict[str, Any]) -> Window:
        """The fingerprint, the size and the session index of the environment's window.

        The database renders the canonical line of every bar; a bar with a missing adjusted value
        is counted instead of rendered and refuses the whole window.
        """
        line = func.concat_ws(
            "|",
            cast(bar.c.instrument_id, Text),
            cast(bar.c.session_date, Text),
            cast(bar.c.revision, Text),
            *(cast(column, Text) for column in ADJUSTED),
        )
        incomplete = or_(*(column.is_(None) for column in ADJUSTED))
        result = await self._session.execute(
            self._in_window(
                select(
                    bar.c.session_date,
                    instrument.c.symbol,
                    incomplete.label("incomplete"),
                    line.label("line"),
                ),
                environment,
            )
        )
        lines: list[str] = []
        per_session: Counter[date] = Counter()
        missing: dict[str, int] = {}
        for day, symbol, has_gap, text_line in result:
            per_session[day] += 1
            if has_gap:
                missing[symbol] = missing.get(symbol, 0) + 1
            else:
                lines.append(text_line)
        if missing:
            raise _missing(missing)
        sessions = {day: index for index, day in enumerate(sorted(per_session))}
        return Window(feeds.fingerprint_of_lines(lines), len(lines), sessions, per_session)

    async def rows(self, environment: dict[str, Any]) -> list[feeds.BarRow]:
        """Every bar of the window as values (for tests and tools; the feed does not use it)."""
        result = await self._session.execute(
            self._in_window(
                select(
                    bar.c.instrument_id,
                    instrument.c.symbol,
                    bar.c.session_date,
                    bar.c.ts,
                    bar.c.revision,
                    *ADJUSTED,
                ),
                environment,
            )
        )
        return [feeds.BarRow(*row) for row in result.all()]

    async def ticks(
        self, environment_id: uuid.UUID, after_seq: int, limit: int
    ) -> tuple[list[dict[str, Any]], int | None, str]:
        """A page of ticks, the cursor for the next page, and the fingerprint of the data served."""
        # first statement of the transaction: the window and the page come from one snapshot
        await self._session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
        environment = await EnvironmentService(self._session).get(environment_id)
        check_replayable(environment)
        window = await self.window(environment)
        result = await self._session.execute(
            self._in_window(
                select(
                    bar.c.instrument_id,
                    instrument.c.symbol,
                    bar.c.session_date,
                    bar.c.ts,
                    bar.c.revision,
                    *ADJUSTED,
                ),
                environment,
            )
            .offset(after_seq)
            .limit(limit)
        )
        items = [
            feeds.tick(
                feeds.BarRow(*row),
                after_seq + offset,
                window.sessions[row.session_date],
                environment["id"],
                window.fingerprint,
            )
            for offset, row in enumerate(result.all(), start=1)
        ]
        more = after_seq + limit < window.total
        return items, (int(items[-1]["seq"]) if items and more else None), window.fingerprint

    async def activate(self, environment_id: uuid.UUID) -> dict[str, Any]:
        """Freeze the fingerprint and mark the environment active; repeating it re-freezes."""
        environment = await EnvironmentService(self._session).get(environment_id)
        check_replayable(environment)
        window = await self.window(environment)
        missing = sum(
            1 for count in window.per_session.values() if count < len(environment["instrument_ids"])
        )
        statement = insert(environment_activation).values(
            environment_id=environment["id"],
            source_fingerprint=window.fingerprint,
            missing_session_count=missing,
            activated_by=self._actor,
        )
        frozen = (
            await self._session.execute(
                statement.on_conflict_do_update(
                    index_elements=[environment_activation.c.environment_id],
                    set_={
                        "source_fingerprint": statement.excluded.source_fingerprint,
                        "missing_session_count": statement.excluded.missing_session_count,
                        "activated_by": statement.excluded.activated_by,
                        "activated_at": func.now(),
                    },
                ).returning(*environment_activation.c)
            )
        ).one()
        await self._session.execute(
            update(market_environment)
            .where(market_environment.c.id == environment["id"])
            .values(status="active", updated_at=func.now())
        )
        return {
            "environment_id": frozen.environment_id,
            "status": "active",
            "source_fingerprint": frozen.source_fingerprint,
            "missing_session_count": frozen.missing_session_count,
            "activated_by": frozen.activated_by,
            "activated_at": frozen.activated_at,
        }
