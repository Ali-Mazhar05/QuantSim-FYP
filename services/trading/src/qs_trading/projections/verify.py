"""Hash-chain verification of a stored trade log (task A15, A-FR-10).

:func:`verify_chain` re-derives every event's hash from the row as stored (the JSONB
payload as read back and the ``event_time``) with :mod:`qs_trading.domain.hashing`, and
checks that ``seq`` runs 1, 2, 3 without gaps and that each ``prev_hash`` is the hash of the
event before. It reports the first ``seq`` where any of that fails, so a changed payload,
time, type, ``seq`` or hash, a missing event and a reordered log are all caught, and the
events before the break are still known to be intact.
"""

import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from qs_trading.domain.hashing import event_hash

__all__ = ["ChainReport", "StoredEvent", "verify_chain"]


@dataclass(frozen=True, slots=True)
class StoredEvent:
    """One ``trade_event`` row as read back from the database."""

    portfolio_id: uuid.UUID
    seq: int
    event_time: datetime
    type: str
    version: int
    payload: Mapping[str, Any]
    prev_hash: str | None
    hash: str

    @classmethod
    def from_row(cls, row: Any) -> "StoredEvent":
        """From a selected ``trade_event`` row (any object with its column attributes)."""
        return cls(
            portfolio_id=row.portfolio_id,
            seq=int(row.seq),
            event_time=row.event_time,
            type=str(row.type),
            version=int(row.version),
            payload=row.payload,
            prev_hash=row.prev_hash,
            hash=row.hash,
        )

    def recomputed_hash(self, prev_hash: str | None) -> str:
        """This row's hash chained onto ``prev_hash``, from its stored columns."""
        return event_hash(
            prev_hash,
            portfolio_id=self.portfolio_id,
            seq=self.seq,
            event_type=self.type,
            version=self.version,
            payload=self.payload,
            event_time=self.event_time,
        )


@dataclass(frozen=True, slots=True)
class ChainReport:
    """The outcome of verifying one portfolio's log. ``last_seq`` and ``last_hash`` are the
    end of the intact prefix: the whole log when it is valid."""

    portfolio_id: uuid.UUID
    events: int
    last_seq: int
    last_hash: str | None
    broken_seq: int | None = None
    reason: str | None = None

    @property
    def valid(self) -> bool:
        return self.broken_seq is None

    def to_json(self) -> dict[str, Any]:
        return {
            "portfolio_id": str(self.portfolio_id),
            "valid": self.valid,
            "events": self.events,
            "last_seq": self.last_seq,
            "last_hash": self.last_hash,
            "broken_seq": self.broken_seq,
            "reason": self.reason,
        }


def _problem(event: StoredEvent, portfolio_id: uuid.UUID, expected: int, prev: str | None) -> str:
    if event.portfolio_id != portfolio_id:
        return f"the event belongs to portfolio {event.portfolio_id}"
    if event.seq != expected:
        return f"expected seq {expected}, found seq {event.seq}"
    if event.prev_hash != prev:
        return "prev_hash is not the hash of the previous event"
    try:
        recomputed = event.recomputed_hash(prev)
    except (TypeError, ValueError) as exc:
        return f"the stored row cannot be hashed: {exc}"
    if recomputed != event.hash:
        return "the stored hash does not match the stored event"
    return ""


def verify_chain(portfolio_id: uuid.UUID, events: Iterable[StoredEvent]) -> ChainReport:
    """Verifies the log of ``portfolio_id``, given in ``seq`` order."""
    previous: str | None = None
    count = 0
    for expected, event in enumerate(events, start=1):
        problem = _problem(event, portfolio_id, expected, previous)
        if problem:
            return ChainReport(portfolio_id, count, expected - 1, previous, expected, problem)
        previous = event.hash
        count += 1
    return ChainReport(portfolio_id, count, count, previous)
