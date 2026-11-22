"""Properties of the built-in strategies over random markets (A12 acceptance, A-FR-03).

Momentum's max-position cap holds after its orders fill at the next price: bars are
gapless (each open is the previous close) and fills pay no cost, so the next price is the
price the orders were sized at. At every session, after that session's fills, no position
is worth more than ``max_position`` of portfolio value, cash never goes negative and no
sale exceeds the holding. Every kind gives the same orders on a rerun.
"""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from qs_trading.domain.accounting import Fill, apply_fill, open_portfolio, portfolio_value
from qs_trading.domain.history import BarHistory
from qs_trading.domain.orders import OrderIntent
from qs_trading.domain.strategies import KINDS, build_strategy
from qs_trading.domain.strategy import Bar, Strategy

SYMBOLS = ["AAA", "BBB", "CCC", "DDD"]
START = datetime(2026, 1, 5, 21, tzinfo=UTC)

closes = st.decimals(min_value="0.5", max_value="800", places=2)
capitals = st.decimals(min_value="500", max_value="5000000", places=2)


@st.composite
def markets(draw: st.DrawFn, min_sessions: int = 2) -> list[Bar]:
    """Gapless bars for 1-4 symbols; a symbol may list late."""
    symbols = SYMBOLS[: draw(st.integers(min_value=1, max_value=len(SYMBOLS)))]
    sessions = draw(st.integers(min_value=min_sessions, max_value=min_sessions + 14))
    bars = []
    for symbol in symbols:
        first = draw(st.integers(min_value=0, max_value=min(2, sessions - 1)))
        series = draw(st.lists(closes, min_size=sessions, max_size=sessions))
        previous = series[first]
        for session in range(first, sessions):
            close = series[session]
            bars.append(
                Bar(
                    session,
                    symbol,
                    START + timedelta(days=session),
                    previous,
                    max(previous, close),
                    min(previous, close),
                    close,
                    Decimal(100_000),
                )
            )
            previous = close
    return bars


momentum_params = st.fixed_dictionaries(
    {
        "lookback": st.integers(min_value=1, max_value=4),
        "top_n": st.integers(min_value=1, max_value=4),
        "rebalance_every": st.integers(min_value=1, max_value=4),
        "max_position": st.decimals(min_value="0.05", max_value="1", places=2),
        "cash_buffer": st.decimals(min_value="0", max_value="0.1", places=3),
    }
)


def run(
    strategy: Strategy, bars: Sequence[Bar], capital: Decimal, cap: Decimal | None
) -> list[Sequence[OrderIntent]]:
    """Run with fills at the next open and no costs; check the cap after each session's
    fills when ``cap`` is given. Returns every session's orders."""
    history = BarHistory(bars)
    opens = {(b.symbol, b.session): b.open for b in bars}
    state = open_portfolio(capital)
    pending: Sequence[OrderIntent] = ()
    placed: list[Sequence[OrderIntent]] = []
    for session in range(max(b.session for b in bars) + 1):
        for order in pending:
            # Every order is for a symbol that traded at t, and it trades again at t + 1
            assert order.quantity > 0
            state = apply_fill(
                state,
                Fill(order.symbol, order.side, order.quantity, opens[(order.symbol, session)]),
            )
        assert state.cash >= 0
        if cap is not None and state.positions:
            marks = {s: opens[(s, session)] for s in state.positions}
            value = portfolio_value(state, marks)
            for symbol, position in state.positions.items():
                assert position.quantity * marks[symbol] <= cap * value, (session, symbol)
        pending = strategy.on_bar(history.view(session, state))
        placed.append(pending)
    return placed


@settings(max_examples=300, deadline=None)
@given(bars=markets(min_sessions=3), params=momentum_params, capital=capitals)
def test_momentum_cap_holds_after_fills(
    bars: list[Bar], params: dict[str, Any], capital: Decimal
) -> None:
    strategy = build_strategy("momentum", params)
    run(strategy, bars, capital, params["max_position"])


@settings(max_examples=100, deadline=None)
@given(bars=markets(), capital=capitals, kind=st.sampled_from(KINDS))
def test_every_kind_is_deterministic(bars: list[Bar], capital: Decimal, kind: str) -> None:
    all_params: dict[str, dict[str, Any]] = {
        "buy_and_hold": {},
        "ma_crossover": {"fast": 1, "slow": 3},
        "momentum": {"lookback": 2, "top_n": 2, "rebalance_every": 2},
        "mean_reversion": {"window": 3, "entry_z": "0.5"},
    }
    params = all_params[kind]
    first = run(build_strategy(kind, params), bars, capital, None)
    second = run(build_strategy(kind, params), list(reversed(bars)), capital, None)
    assert first == second
