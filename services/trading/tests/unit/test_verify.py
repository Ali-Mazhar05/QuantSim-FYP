"""Hash-chain verification of a stored log (A15, A-FR-10): an intact log verifies, and
every kind of change to a stored row is reported at the first seq it breaks.

The rows are the engine's events in their stored form (payload through JSON, as JSONB
gives it back), copied and altered in memory: the database never lets a row change."""

import json
import uuid
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from qs_trading.adapters.file_environment import FileEnvironment
from qs_trading.engine.core import Engine, RunSpec
from qs_trading.engine.runner import load_ticks
from qs_trading.ports.market_environment import EnvironmentRef
from qs_trading.projections import StoredEvent, verify_chain

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/environments/two_symbols_10_sessions.json"
PORTFOLIO = uuid.UUID("0a150000-0000-4000-8000-000000000002")
SPEC = RunSpec(
    portfolio_id=PORTFOLIO,
    strategy_kind="momentum",
    strategy_params={"lookback": 2, "top_n": 1, "rebalance_every": 2, "max_position": "0.9"},
    initial_capital=Decimal("10000"),
    cost_model={"fixed": "1.00", "per_share": "0.01", "pct": "0.0005"},
    slippage_model={"kind": "fixed_bps", "bps": "5"},
    environment=EnvironmentRef("replay", "5d0c6c1e-7a14-4a14-8a14-000000000001"),
)


@pytest.fixture
async def stored() -> list[StoredEvent]:
    environment = FileEnvironment(FIXTURE)
    fingerprint = await environment.activate()
    engine = Engine.prepare(SPEC, fingerprint, await load_ticks(environment, fingerprint))
    return [
        StoredEvent(
            portfolio_id=e.portfolio_id,
            seq=e.seq,
            event_time=e.event_time,
            type=e.type.value,
            version=e.version,
            payload=json.loads(json.dumps(e.payload_json)),
            prev_hash=e.prev_hash,
            hash=e.hash,
        )
        for result in engine.run()
        for e in result.events
    ]


def test_an_intact_log_verifies(stored: list[StoredEvent]) -> None:
    report = verify_chain(PORTFOLIO, stored)
    assert report.valid
    assert (report.events, report.last_seq, report.last_hash) == (
        len(stored),
        stored[-1].seq,
        stored[-1].hash,
    )
    assert report.to_json() == {
        "portfolio_id": str(PORTFOLIO),
        "valid": True,
        "events": len(stored),
        "last_seq": stored[-1].seq,
        "last_hash": stored[-1].hash,
        "broken_seq": None,
        "reason": None,
    }


def test_an_empty_log_verifies() -> None:
    report = verify_chain(PORTFOLIO, [])
    assert report.valid and (report.events, report.last_seq, report.last_hash) == (0, 0, None)


def _altered_at(stored: list[StoredEvent], index: int, event: StoredEvent) -> list[StoredEvent]:
    return [*stored[:index], event, *stored[index + 1 :]]


def _breaks_at(stored: list[StoredEvent], rows: list[StoredEvent], seq: int, reason: str) -> None:
    report = verify_chain(PORTFOLIO, rows)
    assert not report.valid
    assert report.broken_seq == seq
    assert report.reason is not None and reason in report.reason
    # Everything before the break is vouched for
    assert (report.last_seq, report.last_hash) == (
        seq - 1,
        stored[seq - 2].hash if seq > 1 else None,
    )
    assert report.events == seq - 1
    assert report.to_json()["broken_seq"] == seq


def test_a_changed_payload_breaks_at_its_seq(stored: list[StoredEvent]) -> None:
    index = next(i for i, e in enumerate(stored) if e.type == "ORDER_FILLED")
    event = stored[index]
    payload = {**event.payload, "fill_price": "1.00000000"}
    rows = _altered_at(stored, index, replace(event, payload=payload))
    _breaks_at(stored, rows, event.seq, "stored hash does not match")


@pytest.mark.parametrize(
    "change",
    [
        {"type": "ORDER_EXPIRED"},
        {"version": 2},
        {"event_time": "later"},
        {"hash": "0" * 64},
    ],
    ids=["type", "version", "event_time", "hash"],
)
def test_any_changed_column_breaks_at_its_seq(
    stored: list[StoredEvent], change: dict[str, object]
) -> None:
    index = len(stored) // 2
    event = stored[index]
    if change.get("event_time") == "later":
        change = {"event_time": event.event_time + timedelta(microseconds=1)}
    rows = _altered_at(stored, index, replace(event, **change))  # type: ignore[arg-type]
    _breaks_at(stored, rows, event.seq, "stored hash does not match")


def test_a_changed_link_breaks_at_its_seq(stored: list[StoredEvent]) -> None:
    index = 3
    rows = _altered_at(stored, index, replace(stored[index], prev_hash="f" * 64))
    _breaks_at(stored, rows, stored[index].seq, "prev_hash")


def test_a_missing_event_breaks_where_it_was(stored: list[StoredEvent]) -> None:
    rows = [*stored[:4], *stored[5:]]
    _breaks_at(stored, rows, 5, "expected seq 5, found seq 6")


def test_a_reordered_log_breaks_at_the_first_swap(stored: list[StoredEvent]) -> None:
    rows = [*stored[:2], stored[3], stored[2], *stored[4:]]
    _breaks_at(stored, rows, 3, "expected seq 3")


def test_another_portfolios_event_breaks_the_log(stored: list[StoredEvent]) -> None:
    rows = _altered_at(stored, 0, replace(stored[0], portfolio_id=uuid.uuid4()))
    _breaks_at(stored, rows, 1, "belongs to portfolio")


def test_a_row_that_cannot_be_hashed_breaks_the_log(stored: list[StoredEvent]) -> None:
    index = 1
    payload = {**stored[index].payload, "session": 0.5}
    rows = _altered_at(stored, index, replace(stored[index], payload=payload))
    _breaks_at(stored, rows, stored[index].seq, "cannot be hashed")


def test_a_rewritten_tail_verifies_but_ends_on_another_hash(stored: list[StoredEvent]) -> None:
    """Whoever rewrites a row and every hash after it gets a chain that verifies on its
    own; only the recorded final hash (run.completed, the run's job result) exposes it."""
    index = len(stored) - 3
    rows = list(stored[:index])
    for event in stored[index:]:
        previous = rows[-1].hash
        payload = dict(event.payload)
        if event.seq == stored[index].seq:
            payload["session"] = int(payload.get("session", 0)) + 100
        draft = replace(event, payload=payload, prev_hash=previous)
        rows.append(replace(draft, hash=draft.recomputed_hash(previous)))
    report = verify_chain(PORTFOLIO, rows)
    assert report.valid
    assert report.last_hash != stored[-1].hash


def test_a_row_reads_back_from_its_columns(stored: list[StoredEvent]) -> None:
    event = stored[0]

    class Row:
        portfolio_id = event.portfolio_id
        seq = event.seq
        event_time = event.event_time
        type = event.type
        version = event.version
        payload = event.payload
        prev_hash = event.prev_hash
        hash = event.hash

    assert StoredEvent.from_row(Row()) == event
    assert event.recomputed_hash(None) == event.hash
