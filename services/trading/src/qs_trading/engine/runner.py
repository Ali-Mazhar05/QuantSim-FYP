"""The engine run loop (task A14): pulls the ticks, resumes after a crash, and hands each
session's events to a sink that commits them in one transaction.

**Run.** :func:`run_portfolio` activates the environment (which freezes the source
fingerprint), binds that fingerprint to the portfolio, pulls every tick page by page with
``after_seq`` (each page must carry the frozen fingerprint), and runs the sessions in order
with the pure :class:`~qs_trading.engine.core.Engine`. Before each session is committed
the environment's fingerprint is read again, so data that changes under a running engine
stops it with :class:`~qs_trading.ports.market_environment.FingerprintChanged` instead of
mixing two versions of the market into one log.

**Resume (A-FR-13).** Each session commits as a whole, so the committed log always ends
on a session boundary. On start the sink reports the committed ``last_seq`` and
``last_hash``. When ``last_seq`` is above zero the run is recomputed from session 0 in
memory, writing nothing, up to that ``seq``; the recomputed hash must equal the stored one
(else :class:`~qs_trading.engine.core.ResumeMismatch`), and the run then continues with the
next session. Because every session is a pure function of the spec, the ticks and the
state before it, a resumed run appends exactly the events an uninterrupted run would have.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from qs_trading.engine.core import Engine, LoggedEvent, RunSpec, SessionResult
from qs_trading.ports.market_environment import (
    MAX_PAGE_SIZE,
    FingerprintChanged,
    MarketEnvironment,
    Tick,
)

__all__ = [
    "ChainHead",
    "EventSink",
    "MemorySink",
    "Progress",
    "RunResult",
    "load_ticks",
    "run_portfolio",
]

Progress = Callable[[float], Awaitable[None]]
"""Called after each committed session with the share of sessions done (0 to 1)."""


@dataclass(frozen=True, slots=True)
class ChainHead:
    """The end of a portfolio's committed log."""

    last_seq: int = 0
    last_hash: str | None = None


class EventSink(Protocol):
    """Where a run's events go: trading_db (:mod:`~qs_trading.engine.store`) or memory."""

    async def bind_fingerprint(self, fingerprint: str) -> None:
        """Records the fingerprint the run reads under; raises
        :class:`~qs_trading.ports.market_environment.FingerprintChanged` when the portfolio
        is already bound to another one."""
        ...

    async def head(self) -> ChainHead:
        """The committed end of the log."""
        ...

    async def commit(self, engine: Engine, result: SessionResult) -> None:
        """Appends one session's events, and everything derived from them, atomically.
        Raises when the log no longer ends where ``result`` expects it to."""
        ...


@dataclass(frozen=True, slots=True)
class RunResult:
    portfolio_id: str
    source_fingerprint: str
    sessions: int
    resumed_at_session: int  # 0 for a fresh run; the first session this call ran
    final_seq: int
    final_hash: str
    final_value: Decimal

    def to_json(self) -> dict[str, object]:
        return {
            "portfolio_id": self.portfolio_id,
            "source_fingerprint": self.source_fingerprint,
            "sessions": self.sessions,
            "resumed_at_session": self.resumed_at_session,
            "final_seq": self.final_seq,
            "final_hash": self.final_hash,
            "final_value": str(self.final_value),
        }


async def load_ticks(
    environment: MarketEnvironment, fingerprint: str, *, page_size: int = MAX_PAGE_SIZE
) -> list[Tick]:
    """Every tick of the environment, page by page; each page must have been served under
    ``fingerprint``."""
    ticks: list[Tick] = []
    after_seq = 0
    while True:
        page = await environment.ticks(after_seq, page_size)
        if page.fingerprint != fingerprint:
            raise FingerprintChanged(fingerprint, page.fingerprint)
        ticks.extend(page.items)
        if page.next_after_seq is None:
            return ticks
        if page.next_after_seq <= after_seq:
            raise RuntimeError(f"the tick feed did not advance past seq {after_seq}")
        after_seq = page.next_after_seq


async def run_portfolio(
    spec: RunSpec,
    environment: MarketEnvironment,
    sink: EventSink,
    *,
    progress: Progress | None = None,
) -> RunResult:
    """Runs (or resumes) ``spec`` on ``environment`` to the end, committing one session at
    a time to ``sink``. Safe to call again after any failure."""
    if environment.ref != spec.environment:
        raise ValueError(f"the environment is {environment.ref}, the portfolio wants {spec}")
    fingerprint = await environment.activate()
    await sink.bind_fingerprint(fingerprint)
    engine = Engine.prepare(spec, fingerprint, await load_ticks(environment, fingerprint))
    head = await sink.head()
    state, start = engine.replay(head.last_seq, head.last_hash)
    total = len(engine.sessions)
    for index in range(start, total):
        current = await environment.fingerprint()
        if current != fingerprint:
            raise FingerprintChanged(fingerprint, current)
        result = engine.step(state, index)
        await sink.commit(engine, result)
        state = result.state
        if progress is not None:
            await progress((index + 1) / total)
    if state.last_hash is None or state.last_value is None:
        raise RuntimeError("a complete run has a log and a value")
    return RunResult(
        portfolio_id=str(spec.portfolio_id),
        source_fingerprint=fingerprint,
        sessions=total,
        resumed_at_session=start,
        final_seq=state.last_seq,
        final_hash=state.last_hash,
        final_value=state.last_value,
    )


class MemorySink:
    """An :class:`EventSink` in memory: the log as a list, for tests and dry runs."""

    def __init__(self) -> None:
        self.events: list[LoggedEvent] = []
        self.fingerprint: str | None = None
        self.sessions_committed = 0

    async def bind_fingerprint(self, fingerprint: str) -> None:
        if self.fingerprint is None:
            self.fingerprint = fingerprint
        elif self.fingerprint != fingerprint:
            raise FingerprintChanged(self.fingerprint, fingerprint)

    async def head(self) -> ChainHead:
        if not self.events:
            return ChainHead()
        return ChainHead(self.events[-1].seq, self.events[-1].hash)

    async def commit(self, engine: Engine, result: SessionResult) -> None:
        head = await self.head()
        first = result.events[0]
        if (head.last_seq, head.last_hash) != (first.seq - 1, first.prev_hash):
            raise RuntimeError(f"the log ends at seq {head.last_seq}, not {first.seq - 1}")
        self.events.extend(result.events)
        self.sessions_committed += 1
