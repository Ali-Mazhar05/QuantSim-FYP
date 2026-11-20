"""Built-in strategies (A12): params save and reload, bad params name the field (A-FR-01),
hand-derived orders for each kind and momentum under its cap (A-FR-03), determinism."""

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Context, Decimal, localcontext
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from qs_trading.domain.accounting import Fill, PortfolioState, apply_fill, open_portfolio
from qs_trading.domain.history import BarHistory
from qs_trading.domain.orders import OrderIntent, OrderType, Side
from qs_trading.domain.strategies import (
    KINDS,
    PARAMS,
    REGISTRY,
    BuyAndHold,
    MaCrossover,
    MeanReversion,
    Momentum,
    UnknownStrategyKind,
    build_strategy,
    params_model,
    validate_params,
)
from qs_trading.domain.strategy import Bar, Strategy

FIXTURES = Path(__file__).parent.parent / "fixtures" / "strategies"
START = datetime(2026, 1, 5, 21, tzinfo=UTC)

Orders = dict[int, list[tuple[str, str, int]]]


def gapless_bars(closes: Mapping[str, Sequence[str]]) -> list[Bar]:
    """Bars whose open is the previous close, so an order sized at the close of ``t``
    fills at that same price at the open of ``t + 1``."""
    bars = []
    for symbol, series in closes.items():
        previous = Decimal(series[0])
        for session, text in enumerate(series):
            close = Decimal(text)
            bars.append(
                Bar(
                    session,
                    symbol,
                    START + timedelta(days=session),
                    previous,
                    max(previous, close),
                    min(previous, close),
                    close,
                    Decimal(1_000_000),
                )
            )
            previous = close
    return bars


def run(
    strategy: Strategy, bars: Sequence[Bar], capital: str, symbols: Sequence[str] | None = None
) -> tuple[Orders, PortfolioState]:
    """A minimal engine: market orders from ``t`` fill at the open of ``t + 1``, no costs."""
    history = BarHistory(bars, symbols)
    opens = {(b.symbol, b.session): b.open for b in bars}
    last = max(b.session for b in bars)
    state = open_portfolio(capital)
    pending: Sequence[OrderIntent] = ()
    placed: Orders = {}
    for session in range(last + 1):
        for order in pending:
            assert order.order_type is OrderType.MARKET
            fill_price = opens[(order.symbol, session)]
            state = apply_fill(state, Fill(order.symbol, order.side, order.quantity, fill_price))
        pending = strategy.on_bar(history.view(session, state))
        if pending:
            placed[session] = [(o.symbol, o.side.value, o.quantity) for o in pending]
    return placed, state


# --- Parameters: save and reload, and bad values name the field (A-FR-01) ---

SAMPLES: dict[str, dict[str, Any]] = {
    "buy_and_hold": {"weights": {"AAA": "0.6", "BBB": "0.3"}, "cash_buffer": "0.01"},
    "ma_crossover": {"fast": 10, "slow": 30, "cash_buffer": "0.05"},
    "momentum": {"lookback": 90, "top_n": 5, "rebalance_every": 10, "max_position": "0.15"},
    "mean_reversion": {"window": 15, "entry_z": "1.5", "exit_z": "-0.25"},
}


def test_the_four_built_in_kinds_are_registered() -> None:
    assert set(KINDS) == {"buy_and_hold", "ma_crossover", "momentum", "mean_reversion"}
    assert set(PARAMS) == set(REGISTRY) == set(SAMPLES)
    for kind in KINDS:
        assert params_model(kind).kind == kind
        assert build_strategy(kind, {}).kind == kind


@pytest.mark.parametrize("kind", sorted(SAMPLES))
def test_params_save_and_reload(kind: str) -> None:
    params = validate_params(kind, SAMPLES[kind])
    stored = json.loads(json.dumps(params.model_dump(mode="json")))  # as JSONB
    assert validate_params(kind, stored) == params
    assert params_model(kind).model_validate_json(params.model_dump_json()) == params
    strategy = build_strategy(kind, stored)
    assert strategy.params == params  # type: ignore[attr-defined]


@pytest.mark.parametrize("kind", sorted(SAMPLES))
def test_defaults_save_and_reload(kind: str) -> None:
    params = validate_params(kind, {})
    assert validate_params(kind, params.model_dump(mode="json")) == params


def test_fractions_keep_their_decimal_value() -> None:
    params = validate_params("momentum", {"max_position": 0.1, "cash_buffer": 0})
    assert params.model_dump(mode="json")["max_position"] == "0.1"
    from_json = params_model("momentum").model_validate_json('{"max_position": 0.3}')
    assert from_json.max_position == Decimal("0.3")  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("kind", "params", "loc"),
    [
        ("momentum", {"lookback": 0}, ("lookback",)),
        ("momentum", {"lookback": "60"}, ("lookback",)),
        ("momentum", {"lookback": 60.0}, ("lookback",)),
        ("momentum", {"top_n": True}, ("top_n",)),
        ("momentum", {"rebalance_every": 0}, ("rebalance_every",)),
        ("momentum", {"max_position": "1.5"}, ("max_position",)),
        ("momentum", {"max_position": 0}, ("max_position",)),
        ("momentum", {"lookbak": 60}, ("lookbak",)),
        ("ma_crossover", {"fast": 30, "slow": 30}, ("slow",)),
        ("ma_crossover", {"slow": 10}, ("slow",)),  # below the default fast of 20
        ("ma_crossover", {"fast": 0}, ("fast",)),
        ("mean_reversion", {"window": 1}, ("window",)),
        ("mean_reversion", {"entry_z": "-1"}, ("entry_z",)),
        ("mean_reversion", {"entry_z": 2, "exit_z": -2}, ("exit_z",)),
        ("buy_and_hold", {"weights": {"AAA": "0.7", "BBB": "0.4"}}, ("weights",)),
        ("buy_and_hold", {"weights": {"AAA": "0"}}, ("weights", "AAA")),
        ("buy_and_hold", {"weights": {}}, ("weights",)),
        ("buy_and_hold", {"weights": {"": "0.5"}}, ("weights", "")),  # the key itself
        ("buy_and_hold", {"cash_buffer": "0.5"}, ("cash_buffer",)),
        ("buy_and_hold", {"cash_buffer": "abc"}, ("cash_buffer",)),
        ("buy_and_hold", {"cash_buffer": "NaN"}, ("cash_buffer",)),
        ("buy_and_hold", {"cash_buffer": False}, ("cash_buffer",)),
    ],
)
def test_bad_params_name_the_field(kind: str, params: dict[str, Any], loc: tuple[str, ...]) -> None:
    with pytest.raises(ValidationError) as caught:
        validate_params(kind, params)
    assert [error["loc"][: len(loc)] for error in caught.value.errors()] == [loc]
    with pytest.raises(ValidationError):
        build_strategy(kind, params)


def test_unknown_kind() -> None:
    with pytest.raises(UnknownStrategyKind):
        build_strategy("pairs_trading", {})
    with pytest.raises(UnknownStrategyKind):
        validate_params("pairs_trading", {})


# --- Momentum: hand-derived orders under the cap (A-FR-03) ---


def test_momentum_fixture_gives_hand_derived_orders() -> None:
    """lookback 3, top 2, rebalance every 3 sessions (t = 3, 6, 9), cap 40%, no buffer.

    t=3: returns AAA +20%, BBB +10%, CCC -10% -> AAA, BBB at min(1/2, 0.4) = 40% of 10,000:
         AAA floor(4000 / 12) = 333, BBB floor(4000 / 22) = 181. Cash left 2,022.
    t=4, 5: AAA 39.96%, BBB 39.82%, both under the cap: no orders.
    t=6: returns since t=3: CCC +20%, AAA +5%, BBB 0% -> CCC, AAA.
         Value 2,022 + 333 * 12.6 + 181 * 22 = 10,199.80; target 4,079.92 each.
         AAA floor(4079.92 / 12.6) = 323 (sell 10), BBB sold, CCC floor(4079.92 / 54) = 75.
    t=7, 8: AAA 39.90%, CCC 39.71%: no orders.
    t=9: returns since t=6: BBB +5%, AAA 0%, CCC -10% -> BBB, AAA.
         Value 2,080 + 323 * 12.6 + 75 * 48.6 = 9,794.80; target 3,917.92 each.
         AAA floor(3917.92 / 12.6) = 310 (sell 13), CCC sold, BBB floor(3917.92 / 23.1) = 169.
    """
    fixture = json.loads((FIXTURES / "momentum_small.json").read_text())
    strategy = build_strategy("momentum", fixture["params"])
    placed, _ = run(strategy, gapless_bars(fixture["closes"]), fixture["capital"])
    expected = {
        int(t): [(s, side, q) for s, side, q in orders]
        for t, orders in fixture["expected_orders"].items()
    }
    assert placed == expected


def test_momentum_trims_a_position_that_drifts_over_the_cap() -> None:
    # One symbol, cap 50%: bought at t=1, then a rally lifts it over the cap at t=3
    strategy = Momentum.from_params(
        {"lookback": 1, "top_n": 1, "rebalance_every": 100, "max_position": "0.5", "cash_buffer": 0}
    )
    placed, _ = run(strategy, gapless_bars({"AAA": ["10", "10", "10", "10", "20"]}), "1000")
    # t=1: 50% of 1,000 at 10 -> 50 shares. t=4: 50 * 20 = 1,000 of 1,500 (66.7%) -> trim
    # to floor(750 / 20) = 37 shares
    assert placed == {1: [("AAA", "buy", 50)], 4: [("AAA", "sell", 13)]}


def test_momentum_ties_go_to_the_earlier_symbol_and_warm_up_waits() -> None:
    strategy = Momentum.from_params(
        {"lookback": 2, "top_n": 1, "rebalance_every": 5, "max_position": 1, "cash_buffer": 0}
    )
    closes = {"BBB": ["10", "10", "11"], "AAA": ["10", "10", "11"]}
    placed, _ = run(strategy, gapless_bars(closes), "1000", ["BBB", "AAA"])
    assert placed == {2: [("BBB", "buy", 90)]}  # nothing before t = lookback


# --- Moving-average crossover on a hand-built series ---


def test_ma_crossover_signals() -> None:
    """fast 2, slow 3, one symbol, no buffer, capital 1,000.

    t=2: 10, 10, 10 -> equal, no change.   t=3: fast 11 > slow 10.67 -> buy floor(1000/12) = 83.
    t=4: fast 12.5 > slow 11.67, held.     t=5: fast 11 < slow 11.33 -> sell 83.
    t=6, 7: still below, flat.             t=8: fast 9.5 > slow 9 -> cash 751, buy 68.
    """
    strategy = MaCrossover.from_params({"fast": 2, "slow": 3, "cash_buffer": 0})
    closes = {"AAA": ["10", "10", "10", "12", "13", "9", "8", "8", "11"]}
    placed, state = run(strategy, gapless_bars(closes), "1000")
    assert placed == {3: [("AAA", "buy", 83)], 5: [("AAA", "sell", 83)], 8: [("AAA", "buy", 68)]}
    assert state.cash == Decimal("751.00")


def test_ma_crossover_splits_capital_into_equal_slots() -> None:
    strategy = MaCrossover.from_params({"fast": 1, "slow": 2})  # 2% buffer
    closes = {"AAA": ["10", "11"], "BBB": ["50", "49"], "CCC": ["20", "21"]}
    placed, _ = run(strategy, gapless_bars(closes), "3000")
    # slot = 3,000 * 0.98 / 3 = 980: AAA floor(980 / 11) = 89, CCC floor(980 / 21) = 46
    assert placed == {1: [("AAA", "buy", 89), ("CCC", "buy", 46)]}


# --- Mean reversion ---


def test_mean_reversion_enters_below_and_exits_at_the_mean() -> None:
    """window 3, entry 1, exit 0.

    t=2: 10, 11, 10 -> z = -0.71, inside the band.
    t=3: 11, 10, 7  -> mean 9.33, std 1.70, z = -1.37 <= -1: buy floor(1000 / 7) = 142.
    t=4: 10, 7, 9   -> mean 8.67, z = +0.27 >= 0: sell 142.
    t=5: 7, 9, 11   -> z = +1.22, flat: nothing.
    """
    strategy = MeanReversion.from_params({"window": 3, "entry_z": 1, "exit_z": 0, "cash_buffer": 0})
    closes = {"AAA": ["10", "11", "10", "7", "9", "11"]}
    placed, _ = run(strategy, gapless_bars(closes), "1000")
    assert placed == {3: [("AAA", "buy", 142)], 4: [("AAA", "sell", 142)]}


def test_mean_reversion_ignores_a_flat_window() -> None:
    strategy = MeanReversion.from_params({"window": 3, "entry_z": "0.1"})
    placed, _ = run(strategy, gapless_bars({"AAA": ["10"] * 6}), "1000")
    assert placed == {}


# --- Buy and hold ---


def test_buy_and_hold_buys_once_at_equal_weights() -> None:
    strategy = BuyAndHold.from_params({})  # 2% buffer
    closes = {"AAA": ["10", "11", "12"], "BBB": ["25", "20", "30"]}
    placed, _ = run(strategy, gapless_bars(closes), "10000")
    # 9,800 investable, 4,900 each: AAA 490, BBB 196
    assert placed == {0: [("AAA", "buy", 490), ("BBB", "buy", 196)]}


def test_buy_and_hold_with_weights_and_a_late_listing() -> None:
    strategy = BuyAndHold.from_params(
        {"weights": {"AAA": "0.5", "BBB": "0.25", "ZZZ": "0.25"}, "cash_buffer": 0}
    )
    bars = gapless_bars({"AAA": ["10", "10", "10"]}) + [
        b for b in gapless_bars({"BBB": ["40", "40", "40"]}) if b.session >= 1
    ]
    placed, _ = run(strategy, bars, "10000", ["AAA", "BBB"])
    # ZZZ is not in the environment; BBB first trades at t=1 and is bought then, at 25% of
    # the value then (10,000 at flat prices)
    assert placed == {0: [("AAA", "buy", 500)], 1: [("BBB", "buy", 62)]}


def test_buy_and_hold_never_overspends_the_budget() -> None:
    strategy = BuyAndHold.from_params({"weights": {"AAA": "1"}, "cash_buffer": "0.1"})
    placed, state = run(strategy, gapless_bars({"AAA": ["3", "3"]}), "100")
    assert placed == {0: [("AAA", "buy", 30)]}
    assert state.cash == Decimal("10.00")


# --- Determinism ---

DATA = {
    "AAA": ["10", "10.5", "11", "10.2", "9.8", "10.9", "11.6", "11.1", "12.3", "12.0", "11.4"],
    "BBB": ["50", "49", "51", "53", "52", "50.5", "48", "47.2", "49.9", "51.3", "52.8"],
    "CCC": ["5", "5.2", "5.1", "4.9", "5.4", "5.6", "5.3", "5.9", "6.1", "5.8", "6.2"],
}
SMALL: dict[str, dict[str, Any]] = {
    "buy_and_hold": {},
    "ma_crossover": {"fast": 2, "slow": 4},
    "momentum": {"lookback": 2, "top_n": 2, "rebalance_every": 2, "max_position": "0.3"},
    "mean_reversion": {"window": 3, "entry_z": "0.5", "exit_z": "0"},
}


@pytest.mark.parametrize("kind", sorted(SMALL))
def test_two_runs_give_identical_orders(kind: str) -> None:
    bars = gapless_bars(DATA)
    first = run(build_strategy(kind, SMALL[kind]), bars, "25000")
    second = run(build_strategy(kind, SMALL[kind]), list(reversed(bars)), "25000")
    assert first == second
    assert first[0]  # the run traded at all


@pytest.mark.parametrize("kind", sorted(SMALL))
def test_the_callers_decimal_context_does_not_change_the_orders(kind: str) -> None:
    history = BarHistory(gapless_bars(DATA))
    state = apply_fill(open_portfolio("25000"), Fill("AAA", Side.BUY, 333, Decimal("10.5")))
    strategy = build_strategy(kind, SMALL[kind])
    for session in range(len(DATA["AAA"])):
        view = history.view(session, state)
        expected = strategy.on_bar(view)
        with localcontext(Context(prec=4)):
            assert strategy.on_bar(view) == expected


def test_orders_are_long_only_whole_share_market_orders() -> None:
    for kind, params in SMALL.items():
        placed, _ = run(build_strategy(kind, params), gapless_bars(DATA), "25000")
        for orders in placed.values():
            for _, side, quantity in orders:
                assert side in {Side.BUY.value, Side.SELL.value}
                assert isinstance(quantity, int) and quantity > 0
