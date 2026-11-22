"""The hash chain of the trade log (A-FR-10, A-FR-12).

Every row of ``trade_event`` carries ``hash_n = sha256(hash_(n-1) || canonical(event_n))``.
The chain makes the log tamper-evident, and because nothing in it comes from a clock or a
random source, the same spec on the same source fingerprint always ends on the same hash.

**Stored payload.** An event's payload is stored, and hashed, as
:func:`payload_json`: the model's JSON dump (``model_dump(mode="json")``) without the
fields that are ``None``. Decimals are therefore strings exactly as ``str(Decimal)`` writes
them (``"100000.00"``, ``"187.19355000"``), datetimes are ISO 8601 strings, enums their
values. Leaving ``None`` out means a payload model that later gains an optional field
still dumps old events to the same bytes. The rebuild (A15) hashes the stored JSONB
payload as read back, so the payload is never re-derived from a model to be checked.

**Canonical form.** :func:`canonical_event` is the UTF-8 encoding of this JSON object::

    {"event_time": "<UTC, %Y-%m-%dT%H:%M:%S.%fZ>",
     "payload": <the stored payload>,
     "portfolio_id": "<lower-case hyphenated UUID>",
     "seq": <integer>,
     "type": "<EventType value>",
     "version": <integer>}

written with keys sorted at every level, no whitespace (separators ``","`` and ``":"``),
non-ASCII characters as themselves (``ensure_ascii=False``). Floats, NaN and infinities
are refused, so money can only travel as decimal strings (NFR-INT-001). ``event_time`` is
the session's close from the market data, never the wall clock.

**Chain.** :func:`chain_hash` is the lower-case hex SHA-256 of the previous hash as ASCII
(the empty string for ``seq = 1``) followed by the canonical bytes. The previous hash is
always 64 hex digits or empty, so the concatenation is unambiguous.
"""

import hashlib
import json
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from qs_trading.domain.events import Payload

__all__ = ["canonical_event", "chain_hash", "event_hash", "format_event_time", "payload_json"]


def payload_json(payload: Payload) -> dict[str, Any]:
    """The stored (and hashed) JSON form of a payload: its JSON dump without ``None``s."""
    return payload.model_dump(mode="json", exclude_none=True)


def format_event_time(event_time: datetime) -> str:
    """``event_time`` in UTC with microseconds: ``2020-01-02T21:00:00.000000Z``."""
    if event_time.tzinfo is None or event_time.utcoffset() is None:
        raise ValueError("event_time must carry a time zone")
    return event_time.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _refuse_floats(value: Any) -> None:
    if isinstance(value, float):
        raise TypeError(f"a hashed payload cannot hold a float ({value!r}); use a decimal string")
    if isinstance(value, Mapping):
        for item in value.values():
            _refuse_floats(item)
    elif isinstance(value, list | tuple):
        for item in value:
            _refuse_floats(item)


def canonical_event(
    *,
    portfolio_id: uuid.UUID,
    seq: int,
    event_type: str,
    version: int,
    payload: Mapping[str, Any],
    event_time: datetime,
) -> bytes:
    """The canonical bytes of one event (see the module docstring)."""
    if isinstance(seq, bool) or not isinstance(seq, int) or seq < 1:
        raise ValueError(f"seq must be a whole number from 1, got {seq!r}")
    _refuse_floats(payload)
    document = {
        "event_time": format_event_time(event_time),
        "payload": payload,
        "portfolio_id": str(portfolio_id),
        "seq": seq,
        "type": str(event_type),
        "version": version,
    }
    text = json.dumps(
        document, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )
    return text.encode("utf-8")


def chain_hash(prev_hash: str | None, canonical: bytes) -> str:
    """``sha256(prev_hash || canonical)`` as lower-case hex; ``prev_hash`` is ``None`` (or
    empty) for the first event of a portfolio."""
    digest = hashlib.sha256()
    digest.update((prev_hash or "").encode("ascii"))
    digest.update(canonical)
    return digest.hexdigest()


def event_hash(
    prev_hash: str | None,
    *,
    portfolio_id: uuid.UUID,
    seq: int,
    event_type: str,
    version: int,
    payload: Mapping[str, Any],
    event_time: datetime,
) -> str:
    """The hash of one event chained onto ``prev_hash``."""
    canonical = canonical_event(
        portfolio_id=portfolio_id,
        seq=seq,
        event_type=event_type,
        version=version,
        payload=payload,
        event_time=event_time,
    )
    return chain_hash(prev_hash, canonical)
