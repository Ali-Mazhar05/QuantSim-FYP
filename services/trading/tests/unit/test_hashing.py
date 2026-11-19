"""The canonical form and the hash chain of the trade log (A-FR-10, A-FR-12)."""

import hashlib
import uuid
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest

from qs_trading.domain.accounting import Side
from qs_trading.domain.events import OrderRejectedV1, TickV1
from qs_trading.domain.hashing import (
    canonical_event,
    chain_hash,
    event_hash,
    format_event_time,
    payload_json,
)
from qs_trading.domain.orders import OrderType, RejectReason

PORTFOLIO = uuid.UUID("12345678-1234-5678-1234-567812345678")
CLOSE = datetime(2026, 1, 5, 21, 0, tzinfo=UTC)


def _tick_canonical(event_time: datetime = CLOSE) -> bytes:
    payload = TickV1(session=0, ts=CLOSE, first_tick_seq=1, last_tick_seq=2)
    return canonical_event(
        portfolio_id=PORTFOLIO,
        seq=2,
        event_type=payload.type,
        version=payload.version,
        payload=payload_json(payload),
        event_time=event_time,
    )


def test_the_canonical_form_is_sorted_compact_json() -> None:
    assert _tick_canonical() == (
        b'{"event_time":"2026-01-05T21:00:00.000000Z",'
        b'"payload":{"first_tick_seq":1,"last_tick_seq":2,"session":0,'
        b'"ts":"2026-01-05T21:00:00Z"},'
        b'"portfolio_id":"12345678-1234-5678-1234-567812345678",'
        b'"seq":2,"type":"TICK","version":1}'
    )


def test_the_same_instant_in_another_zone_has_the_same_form() -> None:
    plus_five = CLOSE.astimezone(timezone(timedelta(hours=5)))
    assert _tick_canonical(plus_five) == _tick_canonical()


def test_a_naive_event_time_is_refused() -> None:
    with pytest.raises(ValueError, match="time zone"):
        format_event_time(datetime(2026, 1, 5, 21, 0))


def test_the_chain_is_sha256_of_the_previous_hash_then_the_event() -> None:
    canonical = _tick_canonical()
    first = chain_hash(None, canonical)
    assert first == hashlib.sha256(canonical).hexdigest()
    assert chain_hash("", canonical) == first
    second = chain_hash(first, canonical)
    assert second == hashlib.sha256(first.encode() + canonical).hexdigest()
    assert len(second) == 64 and second != first


def test_a_known_event_keeps_its_hash() -> None:
    """A change here changes every stored hash: it needs a new event version, not an
    edit of this number."""
    stored = {"first_tick_seq": 1, "last_tick_seq": 2, "session": 0, "ts": "2026-01-05T21:00:00Z"}
    digest = event_hash(
        None,
        portfolio_id=PORTFOLIO,
        seq=2,
        event_type="TICK",
        version=1,
        payload=stored,
        event_time=CLOSE,
    )
    assert digest == "d8f64cac3a0627ae38e8cbcfb3b8a8c8379c15faf0c19073c2297c162b20b91c"


def test_key_order_of_the_payload_does_not_matter() -> None:
    forward = {"a": "1.00", "b": {"x": 1, "y": 2}}
    backward = {"b": {"y": 2, "x": 1}, "a": "1.00"}
    common: dict[str, Any] = {
        "portfolio_id": PORTFOLIO,
        "seq": 1,
        "event_type": "TICK",
        "version": 1,
    }
    assert canonical_event(payload=forward, event_time=CLOSE, **common) == canonical_event(
        payload=backward, event_time=CLOSE, **common
    )


def test_floats_and_bad_seqs_are_refused() -> None:
    common: dict[str, Any] = {"portfolio_id": PORTFOLIO, "event_type": "TICK", "version": 1}
    with pytest.raises(TypeError, match="float"):
        canonical_event(seq=1, payload={"cash": 1.5}, event_time=CLOSE, **common)
    with pytest.raises(TypeError, match="float"):
        canonical_event(seq=1, payload={"nested": [{"x": 0.1}]}, event_time=CLOSE, **common)
    with pytest.raises(ValueError, match="seq"):
        canonical_event(seq=0, payload={}, event_time=CLOSE, **common)


def test_the_stored_payload_has_decimal_strings_and_no_nones() -> None:
    rejected = OrderRejectedV1(
        session=3,
        symbol="AAA",
        side=Side.BUY,
        quantity=10,
        order_type=OrderType.MARKET,
        reason=RejectReason.INSUFFICIENT_CASH,
    )
    stored = payload_json(rejected)
    assert "order_id" not in stored and "limit_price" not in stored
    assert stored["side"] == "buy" and stored["reason"] == "insufficient_cash"
    limit = rejected.model_copy(update={"limit_price": Decimal("98.00000000"), "order_id": "p:7"})
    assert payload_json(limit)["limit_price"] == "98.00000000"
    assert payload_json(limit)["order_id"] == "p:7"
    assert OrderRejectedV1.model_validate(stored) == rejected
