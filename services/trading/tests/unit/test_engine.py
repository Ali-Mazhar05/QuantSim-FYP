"""The pure engine core (A14) on the two-symbol fixture: the order of one session, fills
checked by hand, the hash chain, determinism (A-FR-12) and the recompute used by resume.

Every test uses capital 10,000, costs ``1.00 + 0.01 / share + 0.05 %`` and 5 bps fixed
slippage unless it says otherwise."""

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, ClassVar

import pytest

from qs_trading.adapters.file_environment import FileEnvironment
from qs_trading.domain.accounting import Side
from qs_trading.domain.events import (
    EventType,
    OrderExpiredV1,
    OrderFilledV1,
    OrderPlacedV1,
    OrderRejectedV1,
    RunStartedV1,
    ValuedV1,
)
from qs_trading.domain.hashing import event_hash
from qs_trading.domain.orders import OrderIntent, OrderType, RejectReason
from qs_trading.domain.strategy import HistoryView
from qs_trading.engine.core import (
    Engine,
    EngineError,
    LoggedEvent,
    ResumeMismatch,
    RunSpec,
    group_sessions,
    order_id_for,
)
from qs_trading.engine.runner import load_ticks
from qs_trading.ports.market_environment import EnvironmentRef, Tick

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/environments/two_symbols_10_sessions.json"
PORTFOLIO = uuid.UUID("0a140000-0000-4000-8000-000000000001")
REF = EnvironmentRef("replay", "5d0c6c1e-7a14-4a14-8a14-000000000001")
COSTS = {"fixed": "1.00", "per_share": "0.01", "pct": "0.0005"}
SLIPPAGE = {"kind": "fixed_bps", "bps": "5"}


def _spec(**changes: Any) -> RunSpec:
    spec = RunSpec(
        portfolio_id=PORTFOLIO,
        strategy_kind="buy_and_hold",
        strategy_params={},
        initial_capital=Decimal("10000"),
        cost_model=COSTS,
        slippage_model=SLIPPAGE,
        environment=REF,
    )
    return replace(spec, **changes)


@pytest.fixture
async def fixture_ticks() -> tuple[str, list[Tick]]:
    environment = FileEnvironment(FIXTURE)
    fingerprint = await environment.activate()
    return fingerprint, await load_ticks(environment, fingerprint, page_size=7)


@dataclass(frozen=True)
class Scripted:
    """Sends the given intents at the given sessions, nothing else."""

    kind: ClassVar[str] = "buy_and_hold"
    script: Mapping[int, Sequence[OrderIntent]]

    def on_bar(self, view: HistoryView) -> Sequence[OrderIntent]:
        return self.script.get(view.session, ())


def _events(engine: Engine) -> list[LoggedEvent]:
    return [event for result in engine.run() for event in result.events]


def _of(events: list[LoggedEvent], kind: type[Any]) -> list[Any]:
    return [e.payload for e in events if isinstance(e.payload, kind)]


# --- buy and hold, by hand ----------------------------------------------------------------


async def test_a_full_run_gives_the_expected_event_sequence(
    fixture_ticks: tuple[str, list[Tick]],
) -> None:
    fingerprint, ticks = fixture_ticks
    results = Engine.prepare(_spec(), fingerprint, ticks).run()
    T = EventType
    by_session = [[e.type for e in r.events] for r in results]
    assert by_session[0] == [T.RUN_STARTED, T.TICK, T.ORDER_PLACED, T.ORDER_PLACED, T.VALUED]
    assert by_session[1] == [T.TICK, T.ORDER_FILLED, T.ORDER_FILLED, T.VALUED]
    assert all(types == [T.TICK, T.VALUED] for types in by_session[2:9])
    assert by_session[9] == [T.TICK, T.VALUED, T.RUN_COMPLETED]
    assert [e.seq for r in results for e in r.events] == list(range(1, 27))


async def test_buy_and_hold_sizes_and_fills_as_derived_by_hand(
    fixture_ticks: tuple[str, list[Tick]],
) -> None:
    """Session 0: value 10,000, investable 9,800, half each: 49 AAA at 100 and 98 BBB at
    50. Session 1 opens at 100 and 50; 5 bps makes 100.05 and 50.025."""
    fingerprint, ticks = fixture_ticks
    events = _events(Engine.prepare(_spec(), fingerprint, ticks))
    placed = _of(events, OrderPlacedV1)
    assert [(p.symbol, p.side, p.quantity, p.session) for p in placed] == [
        ("AAA", Side.BUY, 49, 0),
        ("BBB", Side.BUY, 98, 0),
    ]
    aaa, bbb = _of(events, OrderFilledV1)
    # 49 x 100.05 = 4,902.45; costs 1.00 + 0.49 + 0.0005 x 4,902.45 (2.45) = 3.94
    assert (aaa.session, aaa.reference_price, aaa.fill_price) == (
        1,
        Decimal(100),
        Decimal("100.05"),
    )
    assert (aaa.slippage, aaa.cost_fixed, aaa.cost_per_share) == (
        Decimal("0.05"),
        Decimal("1.00"),
        Decimal("0.49"),
    )
    assert (aaa.cost_percentage, aaa.cost_total, aaa.cash_after) == (
        Decimal("2.45"),
        Decimal("3.94"),
        Decimal("5093.61"),
    )
    # 98 x 50.025 = 4,902.45; costs 1.00 + 0.98 + 2.45 = 4.43
    assert (bbb.fill_price, bbb.cost_total, bbb.cash_after) == (
        Decimal("50.025"),
        Decimal("4.43"),
        Decimal("186.73"),
    )
    assert aaa.order_id == placed[0].order_id == order_id_for(PORTFOLIO, 3)
    valued = _of(events, ValuedV1)
    # Session 3: BBB has no bar and is valued at its session-2 close of 51
    assert valued[3].market_value == 49 * 103 + 98 * 51
    assert valued[-1].portfolio_value == Decimal("186.73") + 49 * 100 + 98 * 54
    assert valued[-1].total_costs == Decimal("8.37")


async def test_every_valuation_keeps_the_pnl_identity(
    fixture_ticks: tuple[str, list[Tick]],
) -> None:
    fingerprint, ticks = fixture_ticks
    for valued in _of(_events(Engine.prepare(_spec(), fingerprint, ticks)), ValuedV1):
        assert valued.portfolio_value == valued.cash + valued.market_value
        assert valued.portfolio_value - 10000 == (
            valued.realised_pnl + valued.unrealised_pnl - valued.total_costs
        )


async def test_run_started_records_the_full_spec_and_fingerprint(
    fixture_ticks: tuple[str, list[Tick]],
) -> None:
    fingerprint, ticks = fixture_ticks
    first = _events(Engine.prepare(_spec(), fingerprint, ticks))[0]
    assert isinstance(first.payload, RunStartedV1)
    assert first.payload.source_fingerprint == fingerprint
    assert first.payload.strategy_params == {"cash_buffer": "0.02", "weights": None}
    assert first.payload.cost_model == COSTS
    assert first.payload.slippage_model == SLIPPAGE
    assert first.payload.initial_capital == Decimal("10000.00")
    assert (first.payload.env_type, first.payload.env_id) == ("replay", REF.env_id)


# --- the chain and determinism ------------------------------------------------------------


async def test_events_are_chained_and_timed_by_the_session_close(
    fixture_ticks: tuple[str, list[Tick]],
) -> None:
    fingerprint, ticks = fixture_ticks
    engine = Engine.prepare(_spec(), fingerprint, ticks)
    previous: str | None = None
    for result in engine.run():
        close = engine.sessions[result.index].ts
        for event in result.events:
            assert event.prev_hash == previous
            assert event.event_time == close
            assert event.hash == event_hash(
                previous,
                portfolio_id=PORTFOLIO,
                seq=event.seq,
                event_type=event.type,
                version=event.version,
                payload=event.payload_json,
                event_time=event.event_time,
            )
            previous = event.hash


async def test_two_runs_end_on_the_same_hash(fixture_ticks: tuple[str, list[Tick]]) -> None:
    fingerprint, ticks = fixture_ticks
    first = Engine.prepare(_spec(), fingerprint, ticks).run()
    second = Engine.prepare(_spec(), fingerprint, list(ticks)).run()
    assert first[-1].state.last_hash == second[-1].state.last_hash
    assert [e.hash for r in first for e in r.events] == [e.hash for r in second for e in r.events]


@pytest.mark.parametrize(
    "change",
    [
        {"cost_model": {**COSTS, "per_share": "0.02"}},
        {"slippage_model": {"kind": "fixed_bps", "bps": "6"}},
        {"strategy_params": {"cash_buffer": "0.05"}},
        {"initial_capital": Decimal("10001")},
        {"portfolio_id": uuid.UUID(int=7)},
    ],
    ids=["cost", "slippage", "params", "capital", "portfolio"],
)
async def test_one_changed_input_changes_the_final_hash(
    fixture_ticks: tuple[str, list[Tick]], change: dict[str, Any]
) -> None:
    fingerprint, ticks = fixture_ticks
    base = Engine.prepare(_spec(), fingerprint, ticks).run()[-1].state.last_hash
    changed = Engine.prepare(_spec(**change), fingerprint, ticks).run()[-1].state.last_hash
    assert changed != base


async def test_another_fingerprint_changes_the_final_hash(
    fixture_ticks: tuple[str, list[Tick]],
) -> None:
    fingerprint, ticks = fixture_ticks
    base = Engine.prepare(_spec(), fingerprint, ticks).run()[-1].state.last_hash
    assert Engine.prepare(_spec(), "sha256:other", ticks).run()[-1].state.last_hash != base


async def test_every_built_in_strategy_runs_the_fixture(
    fixture_ticks: tuple[str, list[Tick]],
) -> None:
    fingerprint, ticks = fixture_ticks
    kinds = {
        "buy_and_hold": {},
        "momentum": {"lookback": 2, "top_n": 1, "rebalance_every": 2, "max_position": "0.6"},
        "ma_crossover": {"fast": 2, "slow": 3},
        "mean_reversion": {"window": 3, "entry_z": "0.5", "exit_z": "0"},
    }
    for kind, params in kinds.items():
        results = Engine.prepare(
            _spec(strategy_kind=kind, strategy_params=params), fingerprint, ticks
        ).run()
        assert results[-1].state.completed
        assert results[-1].events[-1].type is EventType.RUN_COMPLETED


# --- order rules on the fixture (scripted orders) -----------------------------------------


def _scripted(
    fingerprint: str, ticks: list[Tick], script: Mapping[int, Sequence[OrderIntent]]
) -> list[LoggedEvent]:
    return _events(Engine.prepare(_spec(), fingerprint, ticks, strategy=Scripted(script)))


def _limit(symbol: str, quantity: int, limit: str, expires: int) -> OrderIntent:
    return OrderIntent(symbol, Side.BUY, quantity, OrderType.LIMIT, Decimal(limit), expires)


async def test_a_gap_down_through_a_resting_limit_fills_at_the_open(
    fixture_ticks: tuple[str, list[Tick]],
) -> None:
    """Placed at session 3 (close 103) at 98; session 4 opens at 95. Fill 95 x 1.0005 =
    95.0475; notional 950.48; costs 1.00 + 0.10 + 0.48 = 1.58."""
    fingerprint, ticks = fixture_ticks
    events = _scripted(fingerprint, ticks, {3: [_limit("AAA", 10, "98", 3)]})
    (placed,) = _of(events, OrderPlacedV1)
    assert (placed.order_type, placed.limit_price, placed.expires_session) == (
        OrderType.LIMIT,
        Decimal("98.00000000"),
        6,
    )
    (filled,) = _of(events, OrderFilledV1)
    assert (filled.session, filled.order_id) == (4, placed.order_id)
    assert (filled.reference_price, filled.fill_price) == (Decimal(95), Decimal("95.0475"))
    assert (filled.cost_total, filled.cash_after) == (Decimal("1.58"), Decimal("9047.94"))


async def test_a_limit_the_range_never_reaches_expires_and_is_logged(
    fixture_ticks: tuple[str, list[Tick]],
) -> None:
    fingerprint, ticks = fixture_ticks
    events = _scripted(fingerprint, ticks, {5: [_limit("BBB", 5, "40", 2)]})
    (placed,) = _of(events, OrderPlacedV1)
    (expired,) = _of(events, OrderExpiredV1)
    assert (expired.order_id, expired.session) == (placed.order_id, 7)
    assert _of(events, OrderFilledV1) == []


async def test_a_market_order_with_no_bar_at_its_fill_session_is_rejected_with_its_id(
    fixture_ticks: tuple[str, list[Tick]],
) -> None:
    fingerprint, ticks = fixture_ticks
    events = _scripted(fingerprint, ticks, {2: [OrderIntent("BBB", Side.BUY, 10)]})
    (placed,) = _of(events, OrderPlacedV1)
    (rejected,) = _of(events, OrderRejectedV1)
    assert (rejected.order_id, rejected.session) == (placed.order_id, 3)
    assert rejected.reason is RejectReason.NO_PRICE


async def test_intents_that_cannot_be_placed_are_rejected_without_an_order(
    fixture_ticks: tuple[str, list[Tick]],
) -> None:
    fingerprint, ticks = fixture_ticks
    script = {
        1: [OrderIntent("ZZZ", Side.BUY, 1)],
        2: [OrderIntent("AAA", Side.BUY, 1000)],
        3: [OrderIntent("AAA", Side.SELL, 1)],
    }
    events = _scripted(fingerprint, ticks, script)
    assert _of(events, OrderPlacedV1) == []
    reasons = [(r.session, r.reason, r.order_id) for r in _of(events, OrderRejectedV1)]
    assert reasons == [
        (1, RejectReason.UNKNOWN_SYMBOL, None),
        (2, RejectReason.INSUFFICIENT_CASH, None),
        (3, RejectReason.INSUFFICIENT_POSITION, None),
    ]
    assert _of(events, ValuedV1)[-1].portfolio_value == Decimal("10000.00")


async def test_a_sale_placed_this_session_pays_for_the_buys_after_it(
    fixture_ticks: tuple[str, list[Tick]],
) -> None:
    """95 AAA bought at session 1 leave about 450 cash. At session 4 the strategy sells
    them and buys 150 BBB (about 7,730): accepted only because the sale's proceeds are
    credited, and at session 5 the sale fills first and pays for the buy."""
    fingerprint, ticks = fixture_ticks
    switch = [OrderIntent("AAA", Side.SELL, 95), OrderIntent("BBB", Side.BUY, 150)]
    events = _scripted(fingerprint, ticks, {0: [OrderIntent("AAA", Side.BUY, 95)], 4: switch})
    assert _of(events, OrderRejectedV1) == []
    fills = [(f.session, f.symbol, f.side) for f in _of(events, OrderFilledV1)]
    assert fills == [(1, "AAA", Side.BUY), (5, "AAA", Side.SELL), (5, "BBB", Side.BUY)]


async def test_a_limit_sale_is_not_credited(fixture_ticks: tuple[str, list[Tick]]) -> None:
    fingerprint, ticks = fixture_ticks
    sale = OrderIntent("AAA", Side.SELL, 95, OrderType.LIMIT, Decimal("200"), 1)
    switch = [sale, OrderIntent("BBB", Side.BUY, 150)]
    events = _scripted(fingerprint, ticks, {0: [OrderIntent("AAA", Side.BUY, 95)], 4: switch})
    (rejected,) = _of(events, OrderRejectedV1)
    assert (rejected.symbol, rejected.reason) == ("BBB", RejectReason.INSUFFICIENT_CASH)


async def test_a_resting_limit_buy_reserves_its_cash(fixture_ticks: tuple[str, list[Tick]]) -> None:
    fingerprint, ticks = fixture_ticks
    script = {0: [_limit("AAA", 60, "90", 5)], 1: [OrderIntent("BBB", Side.BUY, 100)]}
    events = _scripted(fingerprint, ticks, script)
    (rejected,) = _of(events, OrderRejectedV1)
    assert (rejected.session, rejected.reason) == (1, RejectReason.INSUFFICIENT_CASH)


# --- resume and guards ---------------------------------------------------------------------


async def test_replay_recomputes_to_a_committed_session_boundary(
    fixture_ticks: tuple[str, list[Tick]],
) -> None:
    fingerprint, ticks = fixture_ticks
    engine = Engine.prepare(_spec(), fingerprint, ticks)
    results = engine.run()
    committed = results[3].state
    state, index = engine.replay(committed.last_seq, committed.last_hash)
    assert index == 4 and state == committed
    assert engine.replay(0, None) == (engine.initial_state(), 0)
    final = results[-1].state
    assert engine.replay(final.last_seq, final.last_hash)[1] == len(engine.sessions)


async def test_replay_refuses_a_log_it_cannot_reproduce(
    fixture_ticks: tuple[str, list[Tick]],
) -> None:
    fingerprint, ticks = fixture_ticks
    engine = Engine.prepare(_spec(), fingerprint, ticks)
    committed = engine.run()[3].state
    with pytest.raises(ResumeMismatch, match="changed since the run started"):
        engine.replay(committed.last_seq, "0" * 64)
    with pytest.raises(ResumeMismatch):
        engine.replay(committed.last_seq - 1, committed.last_hash)  # not a session boundary
    with pytest.raises(ResumeMismatch):
        engine.replay(1000, committed.last_hash)
    changed = Engine.prepare(_spec(cost_model={"fixed": "2.00"}), fingerprint, ticks)
    with pytest.raises(ResumeMismatch):
        changed.replay(committed.last_seq, committed.last_hash)


async def test_sessions_run_in_order_and_only_once(fixture_ticks: tuple[str, list[Tick]]) -> None:
    fingerprint, ticks = fixture_ticks
    engine = Engine.prepare(_spec(), fingerprint, ticks)
    with pytest.raises(EngineError, match="cannot follow"):
        engine.step(engine.initial_state(), 1)
    final = engine.run()[-1].state
    with pytest.raises(EngineError, match="complete"):
        engine.step(final, len(engine.sessions))


def _tick(seq: int, session: int, symbol: str) -> Tick:
    one = Decimal(1)
    return Tick(seq, session, symbol, datetime(2026, 1, 5, tzinfo=UTC), one, one, one, one, one)


def test_bad_tick_feeds_are_refused() -> None:
    with pytest.raises(EngineError, match="no ticks"):
        group_sessions([])
    with pytest.raises(EngineError, match="without gaps"):
        group_sessions([_tick(1, 0, "A"), _tick(3, 0, "B")])
    with pytest.raises(EngineError, match="order"):
        group_sessions([_tick(1, 0, "B"), _tick(2, 0, "A")])
    sessions = group_sessions([_tick(1, 0, "A"), _tick(2, 0, "B"), _tick(3, 2, "A")])
    assert [(s.session, s.first_seq, s.last_seq) for s in sessions] == [(0, 1, 2), (2, 3, 3)]


def test_a_run_needs_a_fingerprint() -> None:
    with pytest.raises(EngineError, match="fingerprint"):
        Engine.prepare(_spec(), "", [_tick(1, 0, "A")])
