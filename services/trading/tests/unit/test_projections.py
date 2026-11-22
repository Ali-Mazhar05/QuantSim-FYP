"""The projections folded from the trade log (A15) on the two-symbol fixture: every event
gives its rows, folding session by session onto the committed state row (what the engine
store does) equals folding the whole log from seq 1 (what the rebuild does, A-FR-11), the
stored JSON form folds to the same rows, and the state as of any seq equals the engine's
(A-FR-15)."""

import json
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from decimal import Decimal
from pathlib import Path
from typing import ClassVar

import pytest

from qs_trading.adapters.file_environment import FileEnvironment
from qs_trading.domain.accounting import Position, Side
from qs_trading.domain.events import OrderFilledV1, RunStartedV1, TickV1
from qs_trading.domain.orders import OrderIntent, OrderType
from qs_trading.domain.strategy import HistoryView
from qs_trading.engine.core import Engine, RunSpec, SessionResult
from qs_trading.engine.runner import load_ticks
from qs_trading.engine.store import _folded
from qs_trading.ports.market_environment import EnvironmentRef
from qs_trading.projections import (
    Ledger,
    ProjectedEvent,
    Projection,
    ProjectionError,
    compare_projections,
    fold,
    project_log,
    snapshot_at,
)
from qs_trading.projections.fold import Row, positions_json
from qs_trading.projections.rebuild import rebuild_projection

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/environments/two_symbols_10_sessions.json"
PORTFOLIO = uuid.UUID("0a150000-0000-4000-8000-000000000001")
REF = EnvironmentRef("replay", "5d0c6c1e-7a14-4a14-8a14-000000000001")
COSTS = {"fixed": "1.00", "per_share": "0.01", "pct": "0.0005"}
MOMENTUM = {"lookback": 2, "top_n": 1, "rebalance_every": 2, "max_position": "0.9"}


@dataclass(frozen=True)
class Scripted:
    """Sends the given intents at the given sessions, nothing else."""

    kind: ClassVar[str] = "buy_and_hold"
    script: Mapping[int, Sequence[OrderIntent]]

    def on_bar(self, view: HistoryView) -> Sequence[OrderIntent]:
        return self.script.get(view.session, ())


def _limit(symbol: str, quantity: int, limit: str, expires: int) -> OrderIntent:
    return OrderIntent(symbol, Side.BUY, quantity, OrderType.LIMIT, Decimal(limit), expires)


# Every kind of row and status: a market buy then a sale that closes it, a gap-down limit
# fill, an expiring limit, a market order rejected when it comes to fill (no BBB bar at
# session 3), a placement refused outright, and a limit still resting at the end
SCRIPT: Mapping[int, Sequence[OrderIntent]] = {
    0: [OrderIntent("AAA", Side.BUY, 10)],
    1: [OrderIntent("ZZZ", Side.BUY, 1)],
    2: [OrderIntent("BBB", Side.BUY, 10)],
    3: [_limit("AAA", 10, "98", 3)],
    5: [_limit("BBB", 5, "40", 2), OrderIntent("AAA", Side.SELL, 20)],
    8: [_limit("BBB", 5, "40", 5)],
}

SCENARIOS = ["buy_and_hold", "momentum", "scripted"]


def _spec(kind: str) -> RunSpec:
    return RunSpec(
        portfolio_id=PORTFOLIO,
        strategy_kind="momentum" if kind == "momentum" else "buy_and_hold",
        strategy_params=MOMENTUM if kind == "momentum" else {},
        initial_capital=Decimal("10000"),
        cost_model=COSTS,
        slippage_model={"kind": "volume", "bps": "20"},
        environment=REF,
    )


async def _engine(kind: str) -> Engine:
    environment = FileEnvironment(FIXTURE)
    fingerprint = await environment.activate()
    ticks = await load_ticks(environment, fingerprint)
    strategy = Scripted(SCRIPT) if kind == "scripted" else None
    return Engine.prepare(_spec(kind), fingerprint, ticks, strategy=strategy)


def _projected(results: Sequence[SessionResult]) -> list[ProjectedEvent]:
    return [
        ProjectedEvent(e.seq, e.prev_hash, e.hash, e.payload) for r in results for e in r.events
    ]


def _as_stored(row: Row | None) -> Row:
    """A state row as the database gives it back: the positions through JSON."""
    if row is None:
        return {"last_seq": 0, "last_hash": None, "last_session": None, "cash": 0, "positions": {}}
    return {**row, "positions": json.loads(json.dumps(row["positions"]))}


def _live(portfolio_id: uuid.UUID, results: Sequence[SessionResult]) -> Projection:
    """The tables the engine store writes: each session folded onto the stored state row
    and applied the way :func:`~qs_trading.projections.persist.write_rows` applies it."""
    orders: dict[str, Row] = {}
    fills: dict[int, Row] = {}
    holdings: dict[tuple[int, str], Row] = {}
    values: dict[int, Row] = {}
    state: Row | None = None
    for result in results:
        head = Ledger.from_state_row(portfolio_id, _as_stored(state))
        ledger, rows = _folded(head, result)
        for row in rows.orders:
            assert row["order_id"] not in orders
            orders[row["order_id"]] = dict(row)
        for order_id, status in rows.status_changes:
            orders[order_id]["status"] = status
        fills.update((row["seq"], dict(row)) for row in rows.fills)
        holdings.update(((row["seq"], row["symbol"]), dict(row)) for row in rows.holdings)
        values.update((row["seq"], dict(row)) for row in rows.values)
        state = ledger.state_row()
    return Projection(orders, fills, holdings, values, state)


# --- the rows of each event ---------------------------------------------------------------


@pytest.mark.parametrize("kind", SCENARIOS)
async def test_the_fold_gives_one_row_per_event_and_the_engines_final_state(kind: str) -> None:
    engine = await _engine(kind)
    results = engine.run()
    events = _projected(results)
    ledger, rows = project_log(PORTFOLIO, events)
    types = [e.payload.type.value for e in events]
    assert len(rows.orders) == types.count("ORDER_PLACED")
    assert len(rows.fills) == len(rows.holdings) == types.count("ORDER_FILLED") > 0
    assert len(rows.values) == len(engine.sessions)
    assert rows.status_changes == ()
    final = results[-1]
    assert ledger.state_row() == {
        "portfolio_id": PORTFOLIO,
        "last_seq": final.state.last_seq,
        "last_hash": final.state.last_hash,
        "last_session": final.session,
        "cash": final.state.portfolio.cash,
        "positions": positions_json(final.state.portfolio.positions),
    }
    assert ledger.books is not None
    assert ledger.books.realised_pnl == final.state.portfolio.realised_pnl
    assert ledger.books.total_costs == final.state.portfolio.total_costs


async def test_holdings_follow_each_fill_down_to_a_closed_position() -> None:
    _, rows = project_log(PORTFOLIO, _projected((await _engine("scripted")).run()))
    aaa = [(h["session"], h["quantity"], h["cost_basis"]) for h in rows.holdings]
    fills = {f["seq"]: f for f in rows.fills}
    # Bought 10 at session 1 and 10 at session 4 (the gap-down limit), all 20 sold at 6
    assert [(s, q) for s, q, _ in aaa] == [(1, 10), (4, 20), (6, 0)]
    first, second, closed = rows.holdings
    bought = fills[first["seq"]]
    assert first["cost_basis"] == (10 * bought["fill_price"]).quantize(Decimal("0.01"))
    assert second["cost_basis"] > first["cost_basis"]
    assert closed["cost_basis"] == 0
    assert all(h["symbol"] == "AAA" and h["portfolio_id"] == PORTFOLIO for h in rows.holdings)


async def test_orders_end_with_the_status_their_events_give() -> None:
    _, rows = project_log(PORTFOLIO, _projected((await _engine("scripted")).run()))
    statuses = [
        (o["placed_session"], o["symbol"], o["order_type"], o["status"]) for o in rows.orders
    ]
    assert statuses == [
        (0, "AAA", "market", "filled"),
        (2, "BBB", "market", "rejected"),
        (3, "AAA", "limit", "filled"),
        (5, "BBB", "limit", "expired"),
        (5, "AAA", "market", "filled"),
        (8, "BBB", "limit", "open"),
    ]
    limit = rows.orders[2]
    assert (limit["limit_price"], limit["expires_session"]) == (Decimal("98"), 6)
    assert all(o["placed_seq"] == int(o["order_id"].rsplit(":", 1)[1]) for o in rows.orders)


# --- live equals rebuild (A-FR-11) ----------------------------------------------------------


@pytest.mark.parametrize("kind", SCENARIOS)
async def test_folding_session_by_session_equals_folding_the_whole_log(kind: str) -> None:
    results = (await _engine(kind)).run()
    live = _live(PORTFOLIO, results)
    rebuilt = rebuild_projection(PORTFOLIO, _projected(results))
    assert compare_projections(live, rebuilt) == ()
    assert live == rebuilt


@pytest.mark.parametrize("kind", SCENARIOS)
async def test_the_stored_json_form_folds_to_the_same_rows(kind: str) -> None:
    results = (await _engine(kind)).run()
    stored = [
        ProjectedEvent.from_stored(
            seq=e.seq,
            prev_hash=e.prev_hash,
            hash=e.hash,
            event_type=e.type.value,
            version=e.version,
            payload=json.loads(json.dumps(e.payload_json)),
        )
        for r in results
        for e in r.events
    ]
    assert rebuild_projection(PORTFOLIO, stored) == rebuild_projection(
        PORTFOLIO, _projected(results)
    )


async def test_the_store_refuses_a_session_whose_books_differ_from_the_engines() -> None:
    first = (await _engine("buy_and_hold")).run()[0]
    state = replace(first.state, portfolio=replace(first.state.portfolio, cash=Decimal(1)))
    with pytest.raises(ProjectionError, match="differ from the engine"):
        _folded(Ledger(PORTFOLIO), replace(first, state=state))


# --- comparison ---------------------------------------------------------------------------


async def test_the_comparison_names_every_differing_row() -> None:
    results = (await _engine("scripted")).run()
    rebuilt = rebuild_projection(PORTFOLIO, _projected(results))
    fill_seq = next(iter(rebuilt.fills))
    holding_key = next(iter(rebuilt.holdings))
    value_seq = next(iter(rebuilt.values))
    assert rebuilt.state is not None
    tampered = Projection(
        orders=rebuilt.orders,
        fills={
            **rebuilt.fills,
            fill_seq: {**rebuilt.fills[fill_seq], "cost_total": Decimal("0.01")},
        },
        holdings={k: v for k, v in rebuilt.holdings.items() if k != holding_key},
        values={**rebuilt.values, 9999: {**rebuilt.values[value_seq], "seq": 9999}},
        state={**rebuilt.state, "cash": rebuilt.state["cash"] + 1},
    )
    found = {d.table: d for d in compare_projections(tampered, rebuilt)}
    assert set(found) == {"fill", "holding_history", "portfolio_value", "portfolio_state_current"}
    assert found["fill"].changed == (f"seq={fill_seq} (cost_total)",)
    assert found["holding_history"].missing == (f"seq={holding_key[0]} symbol={holding_key[1]}",)
    assert found["portfolio_value"].unexpected == ("seq=9999",)
    assert found["portfolio_state_current"].changed == ("state (cash)",)
    assert found["fill"].to_json()["changed"] == [f"seq={fill_seq} (cost_total)"]


def test_numbers_compare_by_value_like_the_database() -> None:
    a = Projection(fills={1: {"seq": 1, "fill_price": Decimal("100.05")}})
    b = Projection(fills={1: {"seq": 1, "fill_price": Decimal("100.05000000")}})
    assert compare_projections(a, b) == ()
    assert compare_projections(Projection(), Projection()) == ()


# --- point-in-time state (A-FR-15) --------------------------------------------------------


@pytest.mark.parametrize("kind", SCENARIOS)
async def test_the_state_as_of_each_session_end_equals_the_engines(kind: str) -> None:
    results = (await _engine(kind)).run()
    events = _projected(results)
    live: Row | None = None
    for result in results:
        snapshot = snapshot_at(PORTFOLIO, events, result.state.last_seq)
        assert snapshot.cash == result.state.portfolio.cash
        assert dict(snapshot.positions) == dict(result.state.portfolio.positions)
        assert snapshot.realised_pnl == result.state.portfolio.realised_pnl
        assert snapshot.total_costs == result.state.portfolio.total_costs
        assert snapshot.hash == result.state.last_hash
        assert snapshot.last_value == result.state.last_value
        assert set(snapshot.open_orders) == {o.order_id for o in result.state.open_orders}
        # Equals the state row the store holds after this session
        head = Ledger.from_state_row(PORTFOLIO, _as_stored(live))
        live = _folded(head, result)[0].state_row()
        assert snapshot.state_row() == live


async def test_the_state_inside_a_session_reflects_each_fill() -> None:
    events = _projected((await _engine("buy_and_hold")).run())
    filled = [e for e in events if isinstance(e.payload, OrderFilledV1)]
    first = filled[0]
    assert isinstance(first.payload, OrderFilledV1)
    snapshot = snapshot_at(PORTFOLIO, events, first.seq)
    assert snapshot.cash == first.payload.cash_after
    assert set(snapshot.positions) == {first.payload.symbol}
    assert snapshot.session == first.payload.session
    document = snapshot.to_json()
    assert document["seq"] == first.seq and document["cash"] == str(first.payload.cash_after)
    assert json.loads(json.dumps(document)) == document


async def test_the_state_needs_an_event_at_that_seq() -> None:
    events = _projected((await _engine("buy_and_hold")).run())
    for seq in (0, -1, len(events) + 1):
        with pytest.raises(LookupError):
            snapshot_at(PORTFOLIO, events, seq)
    start = snapshot_at(PORTFOLIO, events, 1)
    assert (start.cash, start.positions, start.session) == (Decimal("10000.00"), {}, None)


# --- what the fold refuses ----------------------------------------------------------------


async def _events() -> list[ProjectedEvent]:
    return _projected((await _engine("buy_and_hold")).run())


async def test_the_fold_refuses_a_gap_and_a_broken_link() -> None:
    events = await _events()
    with pytest.raises(ProjectionError, match="seq 3: expected seq 2"):
        project_log(PORTFOLIO, [events[0], *events[2:]])
    with pytest.raises(ProjectionError, match="prev_hash"):
        project_log(PORTFOLIO, [events[0], replace(events[1], prev_hash="0" * 64)])


async def test_the_fold_refuses_events_before_or_after_the_start() -> None:
    events = await _events()
    tick = events[1]
    assert isinstance(tick.payload, TickV1)
    with pytest.raises(ProjectionError, match="before RUN_STARTED"):
        project_log(PORTFOLIO, [replace(tick, seq=1, prev_hash=None)])
    started = events[0]
    assert isinstance(started.payload, RunStartedV1)
    again = ProjectedEvent(2, started.hash, "x", started.payload)
    with pytest.raises(ProjectionError, match="after the run started"):
        project_log(PORTFOLIO, [started, again])


async def test_the_fold_refuses_a_fill_that_disagrees_with_the_books() -> None:
    events = await _events()
    index, fill = next((i, e) for i, e in enumerate(events) if isinstance(e.payload, OrderFilledV1))
    assert isinstance(fill.payload, OrderFilledV1)
    wrong = fill.payload.model_copy(update={"cash_after": fill.payload.cash_after + 1})
    with pytest.raises(ProjectionError, match="cash after the fill"):
        project_log(PORTFOLIO, [*events[:index], replace(fill, payload=wrong)])
    too_big = fill.payload.model_copy(update={"quantity": 10**6})
    with pytest.raises(ProjectionError, match="does not apply"):
        project_log(PORTFOLIO, [*events[:index], replace(fill, payload=too_big)])


async def test_a_whole_log_must_place_every_order_it_settles() -> None:
    events = await _events()
    index = next(i for i, e in enumerate(events) if isinstance(e.payload, OrderFilledV1))
    # Folding from a later head leaves the fill's order to an earlier session...
    head, _ = fold(Ledger(PORTFOLIO), events[:index])
    _, rows = fold(head, events[index : index + 1])
    assert rows.status_changes[0][1] == "filled"
    # ...which a fold from seq 1 never does, so a log missing the placement is refused
    placed = next(i for i, e in enumerate(events) if e.payload.type.value == "ORDER_PLACED")
    assert placed < index
    stripped = [e.payload for e in events[: index + 1] if e is not events[placed]]
    renumbered: list[ProjectedEvent] = []
    for seq, payload in enumerate(stripped, start=1):
        previous = renumbered[-1].hash if renumbered else None
        renumbered.append(ProjectedEvent(seq, previous, f"h{seq}", payload))
    with pytest.raises(ProjectionError, match="never placed"):
        project_log(PORTFOLIO, renumbered)


def test_an_unknown_payload_is_refused() -> None:
    with pytest.raises(ProjectionError, match="no payload model"):
        ProjectedEvent.from_stored(
            seq=1, prev_hash=None, hash="h", event_type="TICK", version=9, payload={}
        )
    with pytest.raises(ProjectionError, match="no payload model"):
        ProjectedEvent.from_stored(
            seq=1, prev_hash=None, hash="h", event_type="NOPE", version=1, payload={}
        )


def test_an_empty_state_row_is_an_empty_ledger() -> None:
    assert Ledger.from_state_row(PORTFOLIO, _as_stored(None)) == Ledger(PORTFOLIO)
    assert Ledger(PORTFOLIO).state_row() is None
    seeded = Ledger.from_state_row(
        PORTFOLIO,
        {
            "last_seq": 5,
            "last_hash": "h",
            "last_session": 0,
            "cash": Decimal("1.00"),
            "positions": {"AAA": {"quantity": 3, "cost_basis": "300.00"}},
        },
    )
    assert seeded.books is not None
    assert dict(seeded.books.positions) == {"AAA": Position(3, Decimal("300.00"))}
    assert seeded.state_row() == {
        "portfolio_id": PORTFOLIO,
        "last_seq": 5,
        "last_hash": "h",
        "last_session": 0,
        "cash": Decimal("1.00"),
        "positions": {"AAA": {"quantity": 3, "cost_basis": "300.00"}},
    }
