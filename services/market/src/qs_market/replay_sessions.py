"""Replay sessions: a virtual clock over an activated environment (B13, DL-003).

The clock is data, not a process. A session stores the session index it stood at (the anchor), the
server time of that moment, the speed (1, 5 or 20 sessions per second) and whether it is playing.
The position is computed from those on every read, so it survives a restart, every tab gets the same
answer and the clock is a plain argument in tests. Pause, a speed change and a seek each write a new
anchor, in one transaction that holds the row lock, so two controls cannot interleave.
"""

import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import Select, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from qs_market.environments import EnvironmentService
from qs_market.models import (
    bar,
    environment_activation,
    market_environment,
    replay_session,
)
from qs_market.replay import ReplayService, check_replayable
from qs_template.errors import ServiceError

NOT_ACTIVE = "urn:quantsim:problem:environment-not-active"
NOT_FOUND = ServiceError(
    404,
    "Replay session not found",
    "No replay session has this id.",
    type_="urn:quantsim:problem:not-found",
)

Clock = Callable[[], datetime]
Action = Literal["play", "pause", "speed", "seek"]
LIST_LIMIT = 100


def utc_now() -> datetime:
    return datetime.now(UTC)


def position(
    *,
    anchor_index: int,
    anchor_at: datetime,
    speed: int,
    state: str,
    now: datetime,
    last_index: int,
) -> int:
    """Where the clock stands: the anchor while paused, else the anchor plus the whole sessions that
    have elapsed since, never past the last session. Integer microseconds, so 5x for 2 s is exactly
    10 and no float rounding can move a boundary. A clock that reads earlier than the anchor (two
    servers a few milliseconds apart) counts as no time elapsed."""
    if state != "playing":
        return min(anchor_index, last_index)
    elapsed_us = max(0, (now - anchor_at) // timedelta(microseconds=1))
    return min(anchor_index + elapsed_us * speed // 1_000_000, last_index)


class ReplaySessionService:
    def __init__(
        self, session: AsyncSession, *, actor_id: uuid.UUID | None = None, clock: Clock = utc_now
    ) -> None:
        self._session = session
        self._actor = actor_id
        self._clock = clock

    def _select(self) -> Select[Any]:
        # the activation's fingerprint now, beside the one the session was created on, so a reader
        # can see that the environment was activated again after the session began
        return select(
            *replay_session.c,
            environment_activation.c.source_fingerprint.label("current_fingerprint"),
        ).select_from(
            replay_session.outerjoin(
                environment_activation,
                environment_activation.c.environment_id == replay_session.c.environment_id,
            )
        )

    async def _session_date(self, environment_id: uuid.UUID, index: int) -> date | None:
        """The trading date of the session at ``index`` among the sessions present in the window."""
        env = (
            await self._session.execute(
                select(
                    market_environment.c.instrument_ids,
                    market_environment.c.start_date,
                    market_environment.c.end_date,
                ).where(market_environment.c.id == environment_id)
            )
        ).first()
        if env is None:
            return None
        ids = [uuid.UUID(i) for i in env.instrument_ids]
        found = await self._session.execute(
            select(bar.c.session_date)
            .where(
                bar.c.instrument_id.in_(ids),
                bar.c.session_date.between(env.start_date, env.end_date),
            )
            .group_by(bar.c.session_date)
            .order_by(bar.c.session_date)
            .offset(index)
            .limit(1)
        )
        return found.scalar_one_or_none()

    async def _view(self, row: Any, now: datetime) -> dict[str, Any]:
        last_index = row.session_count - 1
        index = position(
            anchor_index=row.anchor_index,
            anchor_at=row.anchor_at,
            speed=row.speed,
            state=row.state,
            now=now,
            last_index=last_index,
        )
        return {
            "id": row.id,
            "environment_id": row.environment_id,
            "state": row.state,
            "speed": row.speed,
            "position": index,
            "session_count": row.session_count,
            "session_date": await self._session_date(row.environment_id, index),
            "finished": row.state == "playing" and index == last_index,
            "source_fingerprint": row.source_fingerprint,
            "current_fingerprint": row.current_fingerprint,
            "server_time": now,
            "created_by": row.created_by,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }

    async def create(self, environment_id: uuid.UUID, speed: int = 1) -> dict[str, Any]:
        """Start a session, paused at the first session of an activated environment."""
        environments = EnvironmentService(self._session)
        environment = await environments.get(environment_id)
        check_replayable(environment)
        if environment["status"] != "active":
            raise ServiceError(
                422,
                "The environment is not active",
                "Activate the environment first: that freezes the data a replay runs on.",
                type_=NOT_ACTIVE,
            )
        window = await ReplayService(self._session).window(environment)
        frozen = (
            await self._session.execute(
                select(environment_activation.c.source_fingerprint).where(
                    environment_activation.c.environment_id == environment_id
                )
            )
        ).scalar_one()
        now = self._clock()
        created = (
            await self._session.execute(
                replay_session.insert()
                .values(
                    id=uuid.uuid4(),
                    environment_id=environment_id,
                    anchor_index=0,
                    anchor_at=now,
                    speed=speed,
                    state="paused",
                    session_count=len(window.sessions),
                    source_fingerprint=frozen,
                    created_by=self._actor,
                    created_at=now,
                    updated_at=now,
                )
                .returning(replay_session.c.id)
            )
        ).scalar_one()
        return await self.get(created)

    async def get(self, session_id: uuid.UUID) -> dict[str, Any]:
        row = (
            await self._session.execute(self._select().where(replay_session.c.id == session_id))
        ).first()
        if row is None:
            raise NOT_FOUND
        return await self._view(row, self._clock())

    async def list_for(self, environment_id: uuid.UUID | None) -> list[dict[str, Any]]:
        """Newest first, so a page that was reloaded finds the session it was driving."""
        query = (
            self._select()
            .order_by(replay_session.c.created_at.desc(), replay_session.c.id)
            .limit(LIST_LIMIT)
        )
        if environment_id is not None:
            query = query.where(replay_session.c.environment_id == environment_id)
        now = self._clock()
        return [await self._view(row, now) for row in (await self._session.execute(query)).all()]

    async def control(
        self, session_id: uuid.UUID, action: Action, *, speed: int | None = None, index: int = 0
    ) -> dict[str, Any]:
        """Play, pause, change speed or seek. Repeating what is already true changes nothing, so a
        double click cannot lose the fraction of a session that has elapsed."""
        row = (
            await self._session.execute(
                self._select()
                .where(replay_session.c.id == session_id)
                .with_for_update(of=replay_session)
            )
        ).first()
        if row is None:
            raise NOT_FOUND
        now = self._clock()
        last_index = row.session_count - 1
        here = position(
            anchor_index=row.anchor_index,
            anchor_at=row.anchor_at,
            speed=row.speed,
            state=row.state,
            now=now,
            last_index=last_index,
        )
        change: dict[str, Any] = {}
        if action == "play" and row.state != "playing":
            change = {"state": "playing", "anchor_index": here}
        elif action == "pause" and row.state == "playing":
            change = {"state": "paused", "anchor_index": here}
        elif action == "speed" and speed is not None and speed != row.speed:
            change = {"speed": speed, "anchor_index": here}
        elif action == "seek":
            change = {"anchor_index": max(0, min(index, last_index))}
        if not change:
            return await self._view(row, now)
        await self._session.execute(
            update(replay_session)
            .where(replay_session.c.id == session_id)
            .values(**change, anchor_at=now, updated_at=now)
        )
        return await self.get(session_id)
