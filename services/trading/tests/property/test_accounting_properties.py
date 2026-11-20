"""Properties of the accounting core over random fill sequences (A10 acceptance).

At every step: value = cash + sum(qty * mark); cash is never negative; the P&L identity
holds exactly, including costs. A refused fill leaves the state unchanged.
"""

from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from qs_trading.domain.accounting import (
    AccountingError,
    Fill,
    PortfolioState,
    Side,
    apply_fill,
    market_value,
    open_portfolio,
    portfolio_value,
    unrealised_pnl,
)

SYMBOLS = ["AAPL", "MSFT", "NVDA"]

prices = st.decimals(min_value="0.01", max_value="5000", places=8)
costs = st.decimals(min_value="0", max_value="25", places=2)
fills = st.builds(
    Fill,
    symbol=st.sampled_from(SYMBOLS),
    side=st.sampled_from(list(Side)),
    quantity=st.integers(min_value=1, max_value=500),
    price=prices,
    cost=costs,
)
capitals = st.decimals(min_value="100", max_value="10000000", places=2)
marks = st.fixed_dictionaries({s: prices for s in SYMBOLS})


def assert_books_balance(state: PortfolioState, mark: dict[str, Decimal]) -> None:
    value = portfolio_value(state, mark)
    assert value == state.cash + market_value(state, mark)
    assert state.cash >= 0
    assert value - state.initial_capital == (
        state.realised_pnl + unrealised_pnl(state, mark) - state.total_costs
    )
    for position in state.positions.values():
        assert position.quantity > 0
        assert position.cost_basis >= 0


@settings(max_examples=300, deadline=None)
@given(capital=capitals, sequence=st.lists(fills, max_size=40), mark=marks)
def test_books_balance_after_every_fill(
    capital: Decimal, sequence: list[Fill], mark: dict[str, Decimal]
) -> None:
    state = open_portfolio(capital)
    assert_books_balance(state, mark)
    for fill in sequence:
        try:
            state = apply_fill(state, fill)
        except AccountingError:
            continue
        assert_books_balance(state, mark)


@settings(max_examples=200, deadline=None)
@given(capital=capitals, sequence=st.lists(fills, max_size=20))
def test_a_refused_fill_leaves_the_state_unchanged(capital: Decimal, sequence: list[Fill]) -> None:
    state = open_portfolio(capital)
    for fill in sequence:
        before = state
        try:
            state = apply_fill(state, fill)
        except AccountingError:
            assert state is before
            assert state == before


@settings(max_examples=200, deadline=None)
@given(
    capital=capitals,
    quantity=st.integers(min_value=1, max_value=500),
    price=prices,
)
def test_round_trip_at_the_same_price_without_costs_returns_the_capital(
    capital: Decimal, quantity: int, price: Decimal
) -> None:
    state = open_portfolio(capital)
    try:
        state = apply_fill(state, Fill("AAPL", Side.BUY, quantity, price))
    except AccountingError:
        return
    state = apply_fill(state, Fill("AAPL", Side.SELL, quantity, price))
    assert state.cash == state.initial_capital
    assert state.realised_pnl == 0
    assert dict(state.positions) == {}


@settings(max_examples=100, deadline=None)
@given(capital=capitals, sequence=st.lists(fills, max_size=30))
def test_the_same_fills_give_the_same_state(capital: Decimal, sequence: list[Fill]) -> None:
    def run() -> PortfolioState:
        state = open_portfolio(capital)
        for fill in sequence:
            try:
                state = apply_fill(state, fill)
            except AccountingError:
                pass
        return state

    first, second = run(), run()
    assert first == second
