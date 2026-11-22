"""Hand-computed fixtures for the accounting core (A10)."""

from decimal import Decimal as D

import pytest

from qs_trading.domain.accounting import (
    Fill,
    InsufficientCash,
    InsufficientPosition,
    MissingMark,
    Side,
    apply_fill,
    market_value,
    open_portfolio,
    portfolio_value,
    unrealised_pnl,
)


def buy(symbol: str, qty: int, px: str, cost: str = "0") -> Fill:
    return Fill(symbol, Side.BUY, qty, D(px), D(cost))


def sell(symbol: str, qty: int, px: str, cost: str = "0") -> Fill:
    return Fill(symbol, Side.SELL, qty, D(px), D(cost))


def test_open_portfolio_holds_only_cash() -> None:
    state = open_portfolio("1000000")
    assert state.cash == D("1000000.00")
    assert state.initial_capital == D("1000000.00")
    assert dict(state.positions) == {}
    assert state.realised_pnl == 0
    assert state.total_costs == 0


@pytest.mark.parametrize("bad", ["0", "-5"])
def test_capital_must_be_positive(bad: str) -> None:
    with pytest.raises(ValueError, match="above zero"):
        open_portfolio(bad)


def test_worked_example_buy_buy_partial_sell() -> None:
    """Every number below is computed by hand.

    buy 10 @ 150.25, cost 1   notional 1502.50   cash 10000 - 1503.50 = 8496.50
    buy 5  @ 160.10, cost 1   notional  800.50   cash 8496.50 - 801.50 = 7695.00
                              basis 2303.00 for 15 shares, average 153.53333333
    sell 6 @ 170.00, cost 1   proceeds 1020.00   released 2303 * 6 / 15 = 921.20
                              realised 98.80     cash 7695 + 1020 - 1 = 8714.00
                              left 9 shares, basis 1381.80
    mark 165                  market value 1485  value 10199.00
                              unrealised 103.20  costs 3.00
    identity                  10199 - 10000 = 98.80 + 103.20 - 3.00 = 199.00
    """
    state = open_portfolio("10000")
    state = apply_fill(state, buy("AAPL", 10, "150.25", "1"))
    assert state.cash == D("8496.50")

    state = apply_fill(state, buy("AAPL", 5, "160.10", "1"))
    assert state.cash == D("7695.00")
    position = state.positions["AAPL"]
    assert position.quantity == 15
    assert position.cost_basis == D("2303.00")
    assert position.average_cost == D("153.53333333")

    state = apply_fill(state, sell("AAPL", 6, "170", "1"))
    assert state.cash == D("8714.00")
    assert state.realised_pnl == D("98.80")
    assert state.positions["AAPL"].quantity == 9
    assert state.positions["AAPL"].cost_basis == D("1381.80")
    assert state.total_costs == D("3.00")

    marks = {"AAPL": "165"}
    assert market_value(state, marks) == D("1485")
    assert portfolio_value(state, marks) == D("10199.00")
    assert unrealised_pnl(state, marks) == D("103.20")
    assert portfolio_value(state, marks) - state.initial_capital == (
        state.realised_pnl + unrealised_pnl(state, marks) - state.total_costs
    )


def test_selling_everything_closes_the_position() -> None:
    state = apply_fill(open_portfolio("5000"), buy("MSFT", 3, "333.33", "0.50"))
    state = apply_fill(state, sell("MSFT", 3, "340.00", "0.50"))
    assert "MSFT" not in state.positions
    # proceeds 1020.00 - basis 999.99 = 20.01
    assert state.realised_pnl == D("20.01")
    assert state.cash == D("5000") - D("999.99") - D("0.50") + D("1020.00") - D("0.50")


def test_notional_is_rounded_to_cents_half_to_even() -> None:
    assert buy("X", 1, "0.125").notional == D("0.12")
    assert buy("X", 3, "0.005").notional == D("0.02")


def test_buy_without_enough_cash_is_refused_and_changes_nothing() -> None:
    state = open_portfolio("100")
    with pytest.raises(InsufficientCash):
        apply_fill(state, buy("NVDA", 1, "99.50", "1"))
    assert state.cash == D("100.00")
    assert dict(state.positions) == {}


def test_spending_exactly_all_cash_is_allowed() -> None:
    state = apply_fill(open_portfolio("100"), buy("NVDA", 1, "99.00", "1"))
    assert state.cash == D("0.00")


@pytest.mark.parametrize("qty", [1, 11])
def test_selling_shares_not_held_is_refused(qty: int) -> None:
    state = open_portfolio("10000")
    if qty > 1:
        state = apply_fill(state, buy("AMZN", 10, "100"))
    with pytest.raises(InsufficientPosition):
        apply_fill(state, sell("AMZN", qty, "100"))


def test_a_cost_larger_than_cash_plus_proceeds_is_refused() -> None:
    state = apply_fill(open_portfolio("100"), buy("GOOGL", 1, "100"))
    with pytest.raises(InsufficientCash):
        apply_fill(state, sell("GOOGL", 1, "0.01", "5"))


def test_state_is_immutable() -> None:
    state = open_portfolio("1000")
    after = apply_fill(state, buy("AAPL", 1, "10"))
    assert dict(state.positions) == {}
    assert state.cash == D("1000.00")
    assert after.cash == D("990.00")
    with pytest.raises(TypeError):
        after.positions["AAPL"] = after.positions["AAPL"]  # type: ignore[index]


def test_valuing_a_holding_without_a_mark_is_refused() -> None:
    state = apply_fill(open_portfolio("1000"), buy("AAPL", 1, "10"))
    with pytest.raises(MissingMark):
        portfolio_value(state, {})


@pytest.mark.parametrize(
    ("kwargs", "error"),
    [
        ({"quantity": 0}, ValueError),
        ({"quantity": -1}, ValueError),
        ({"quantity": True}, TypeError),
        ({"quantity": 1.0}, TypeError),
        ({"price": D("0")}, ValueError),
        ({"price": 1.5}, TypeError),
        ({"cost": D("-0.01")}, ValueError),
        ({"symbol": ""}, ValueError),
        ({"side": "short"}, ValueError),
    ],
)
def test_invalid_fills_are_refused(kwargs: dict[str, object], error: type[Exception]) -> None:
    fields: dict[str, object] = {
        "symbol": "AAPL",
        "side": Side.BUY,
        "quantity": 1,
        "price": D("1"),
        "cost": D("0"),
    }
    fields.update(kwargs)
    with pytest.raises(error):
        Fill(**fields)  # type: ignore[arg-type]
