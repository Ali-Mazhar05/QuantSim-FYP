"""Hand-computed fixtures for the execution rules (A-FR-05 to A-FR-07)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import pytest

from qs_trading.domain.accounting import (
    Fill,
    PortfolioState,
    Side,
    apply_fill,
    open_portfolio,
)
from qs_trading.domain.costs import CostBreakdown, LinearCostModel
from qs_trading.domain.execution import (
    Expiry,
    expiry_session,
    limit_reference,
    place_order,
    process_order,
    required_cash,
    validate_intent,
)
from qs_trading.domain.orders import (
    Execution,
    Order,
    OrderIntent,
    OrderStatus,
    OrderType,
    Rejection,
    RejectReason,
)
from qs_trading.domain.slippage import FixedBpsSlippage, VolumeSlippage
from qs_trading.domain.strategy import Bar

T0 = datetime(2026, 1, 2, 21, tzinfo=UTC)
COSTS = LinearCostModel(fixed=D("1.00"), per_share=D("0.005"), pct=D("0.0005"))
FREE = LinearCostModel()
FIVE_BPS = FixedBpsSlippage(bps=D("5"))
NO_SLIP = FixedBpsSlippage()


def bar(
    session: int,
    o: str,
    h: str,
    lo: str,
    c: str,
    volume: str = "1000000",
    symbol: str = "AAPL",
) -> Bar:
    return Bar(session, symbol, T0 + timedelta(days=session), D(o), D(h), D(lo), D(c), D(volume))


def market(side: Side, qty: int, symbol: str = "AAPL") -> OrderIntent:
    return OrderIntent(symbol, side, qty)


def limit(side: Side, qty: int, px: str, expires_after: int | None = None) -> OrderIntent:
    return OrderIntent("AAPL", side, qty, OrderType.LIMIT, D(px), expires_after)


def order(intent: OrderIntent, session: int = 0) -> Order:
    return place_order(intent, order_id="o1", seq=7, session=session)


def holding(qty: int, px: str, cash: str = "100000") -> PortfolioState:
    return apply_fill(open_portfolio(cash), Fill("AAPL", Side.BUY, qty, D(px)))


class TestMarketOrders:
    def test_buy_fills_at_next_open_plus_slippage_and_pays_every_cost(self) -> None:
        state = open_portfolio("100000")
        result = process_order(
            order(market(Side.BUY, 10)),
            session=1,
            bar=bar(1, "100", "102", "99", "101"),
            state=state,
            costs=COSTS,
            slippage=FIVE_BPS,
        )
        # open 100 + 5 bps = 100.05; notional 1000.50
        # costs: fixed 1.00 + 10 * 0.005 = 0.05 + 0.0005 * 1000.50 = 0.50 -> 1.55
        assert isinstance(result, Execution)
        assert result.order_id == "o1"
        assert result.session == 1
        assert result.reference_price == D("100.00000000")
        assert result.fill.price == D("100.05000000")
        assert result.slippage == D("0.05000000")
        assert result.costs == CostBreakdown(D("1.00"), D("0.05"), D("0.50"))
        assert result.fill.cost == D("1.55")
        after = apply_fill(state, result.fill)
        assert after.cash == D("98997.95")  # 100000 - 1000.50 - 1.55

    def test_sale_fills_at_next_open_minus_slippage(self) -> None:
        state = holding(10, "90")
        result = process_order(
            order(market(Side.SELL, 10)),
            session=1,
            bar=bar(1, "100", "102", "99", "101"),
            state=state,
            costs=COSTS,
            slippage=FIVE_BPS,
        )
        # 100 - 5 bps = 99.95; notional 999.50; costs 1.00 + 0.05 + 0.49975 -> 0.50 = 1.55
        assert isinstance(result, Execution)
        assert result.fill.price == D("99.95000000")
        assert result.costs.total == D("1.55")
        assert apply_fill(state, result.fill).cash == D("100097.95")  # 99100 + 999.50 - 1.55

    def test_volume_slippage_on_a_market_buy(self) -> None:
        # 10 bps * 2000 / 400,000 = 0.05 bps; 80 * 1.000005 = 80.0004
        result = process_order(
            order(market(Side.BUY, 2000)),
            session=1,
            bar=bar(1, "80", "81", "79", "80", volume="400000"),
            state=open_portfolio("1000000"),
            costs=FREE,
            slippage=VolumeSlippage(bps=D("10")),
        )
        assert isinstance(result, Execution)
        assert result.fill.price == D("80.00040000")
        assert result.slippage == D("0.00040000")

    def test_never_fills_on_the_session_it_was_placed_in(self) -> None:
        result = process_order(
            order(market(Side.BUY, 1), session=3),
            session=3,
            bar=bar(3, "100", "100", "100", "100"),
            state=open_portfolio("1000"),
            costs=FREE,
            slippage=NO_SLIP,
        )
        assert result is None

    def test_no_bar_at_the_fill_session_is_rejected(self) -> None:
        result = process_order(
            order(market(Side.BUY, 1)),
            session=1,
            bar=None,
            state=open_portfolio("1000"),
            costs=FREE,
            slippage=NO_SLIP,
        )
        assert isinstance(result, Rejection)
        assert result.reason is RejectReason.NO_PRICE

    def test_a_gap_up_the_books_cannot_pay_is_rejected_at_the_fill(self) -> None:
        # placed against a 100 close with 1001 cash; it opens at 110
        state = open_portfolio("1001")
        intent = market(Side.BUY, 10)
        assert (
            validate_intent(
                intent,
                state,
                session=0,
                last_price=D("100"),
                bar_volume=D("1000000"),
                costs=LinearCostModel(fixed=D("1")),
                slippage=NO_SLIP,
            )
            is None
        )
        result = process_order(
            order(intent),
            session=1,
            bar=bar(1, "110", "111", "109", "110"),
            state=state,
            costs=LinearCostModel(fixed=D("1")),
            slippage=NO_SLIP,
        )
        assert isinstance(result, Rejection)
        assert result.reason is RejectReason.INSUFFICIENT_CASH
        assert result.session == 1
        assert state.cash == D("1001.00")


class TestLimitOrders:
    def test_buy_limit_crossed_intraday_fills_at_the_limit(self) -> None:
        state = open_portfolio("100000")
        result = process_order(
            order(limit(Side.BUY, 10, "98")),
            session=1,
            bar=bar(1, "100", "101", "97", "99"),
            state=state,
            costs=COSTS,
            slippage=FIVE_BPS,
        )
        # reference 98; 98 + 5 bps = 98.049 is capped at the limit 98
        # costs: 1.00 + 0.05 + 0.0005 * 980.00 = 0.49 -> 1.54
        assert isinstance(result, Execution)
        assert result.reference_price == D("98.00000000")
        assert result.fill.price == D("98.00000000")
        assert result.slippage == 0
        assert result.costs.total == D("1.54")
        assert apply_fill(state, result.fill).cash == D("99018.46")

    def test_sell_limit_crossed_intraday_fills_at_the_limit(self) -> None:
        result = process_order(
            order(limit(Side.SELL, 5, "104")),
            session=1,
            bar=bar(1, "100", "105", "99", "103"),
            state=holding(5, "90"),
            costs=FREE,
            slippage=FIVE_BPS,
        )
        assert isinstance(result, Execution)
        assert result.fill.price == D("104.00000000")

    def test_gap_down_through_a_buy_limit_fills_at_the_open(self) -> None:
        state = open_portfolio("100000")
        result = process_order(
            order(limit(Side.BUY, 10, "98")),
            session=1,
            bar=bar(1, "95", "96", "94", "95.50"),
            state=state,
            costs=COSTS,
            slippage=FIVE_BPS,
        )
        # reference is the open 95; 95 * 1.0005 = 95.0475, still inside the limit
        # notional 950.48 (950.475 half-even); costs 1.00 + 0.05 + 0.47524 -> 0.48 = 1.53
        assert isinstance(result, Execution)
        assert result.reference_price == D("95.00000000")
        assert result.fill.price == D("95.04750000")
        assert result.slippage == D("0.04750000")
        assert result.fill.notional == D("950.48")
        assert result.costs == CostBreakdown(D("1.00"), D("0.05"), D("0.48"))
        assert apply_fill(state, result.fill).cash == D("99047.99")

    def test_gap_up_through_a_sell_limit_fills_at_the_open(self) -> None:
        result = process_order(
            order(limit(Side.SELL, 4, "105")),
            session=1,
            bar=bar(1, "110", "112", "108", "111"),
            state=holding(4, "90"),
            costs=FREE,
            slippage=FIVE_BPS,
        )
        # 110 * 0.9995 = 109.945
        assert isinstance(result, Execution)
        assert result.reference_price == D("110.00000000")
        assert result.fill.price == D("109.94500000")

    def test_slippage_never_pushes_a_gap_fill_past_the_limit(self) -> None:
        # open 97.99 under a 98 limit; 97.99 + 5 bps = 98.038995 is capped at 98
        result = process_order(
            order(limit(Side.BUY, 1, "98")),
            session=1,
            bar=bar(1, "97.99", "99", "97", "98"),
            state=open_portfolio("1000"),
            costs=FREE,
            slippage=FIVE_BPS,
        )
        assert isinstance(result, Execution)
        assert result.fill.price == D("98.00000000")
        assert result.slippage == D("0.01000000")

    def test_rests_while_the_range_does_not_reach_it(self) -> None:
        result = process_order(
            order(limit(Side.BUY, 10, "90", expires_after=3)),
            session=1,
            bar=bar(1, "100", "101", "95", "99"),
            state=open_portfolio("100000"),
            costs=FREE,
            slippage=NO_SLIP,
        )
        assert result is None

    def test_a_never_reached_limit_expires_on_its_last_session(self) -> None:
        resting = order(limit(Side.BUY, 10, "90", expires_after=2))
        assert resting.expires_session == 2
        sessions = [bar(1, "100", "101", "95", "99"), bar(2, "99", "100", "92", "93")]
        outcomes = [
            process_order(
                resting,
                session=b.session,
                bar=b,
                state=open_portfolio("100000"),
                costs=FREE,
                slippage=NO_SLIP,
            )
            for b in sessions
        ]
        assert outcomes == [None, Expiry("o1", 2)]

    def test_a_limit_can_still_fill_on_its_last_session(self) -> None:
        result = process_order(
            order(limit(Side.BUY, 1, "90", expires_after=2)),
            session=2,
            bar=bar(2, "95", "96", "89", "90"),
            state=open_portfolio("1000"),
            costs=FREE,
            slippage=NO_SLIP,
        )
        assert isinstance(result, Execution)
        assert result.fill.price == D("90.00000000")

    def test_expires_on_its_last_session_without_a_bar(self) -> None:
        result = process_order(
            order(limit(Side.BUY, 1, "90", expires_after=1)),
            session=1,
            bar=None,
            state=open_portfolio("1000"),
            costs=FREE,
            slippage=NO_SLIP,
        )
        assert result == Expiry("o1", 1)

    def test_an_order_offered_past_its_last_session_expires_without_filling(self) -> None:
        result = process_order(
            order(limit(Side.BUY, 1, "90", expires_after=1)),
            session=4,
            bar=bar(4, "80", "81", "79", "80"),
            state=open_portfolio("1000"),
            costs=FREE,
            slippage=NO_SLIP,
        )
        assert result == Expiry("o1", 4)

    def test_without_an_expiry_it_rests_until_the_end_of_the_run(self) -> None:
        resting = order(limit(Side.BUY, 1, "1"))
        assert resting.expires_session is None
        result = process_order(
            resting,
            session=500,
            bar=bar(500, "100", "100", "100", "100"),
            state=open_portfolio("1000"),
            costs=FREE,
            slippage=NO_SLIP,
        )
        assert result is None

    @pytest.mark.parametrize(
        ("side", "px", "expected"),
        [
            (Side.BUY, "100", D("100")),  # open equals the limit
            (Side.BUY, "97", D("97")),  # low touches the limit
            (Side.BUY, "96.99", None),
            (Side.SELL, "100", D("100")),
            (Side.SELL, "102", D("102")),  # high touches the limit
            (Side.SELL, "102.01", None),
        ],
    )
    def test_limit_reference(self, side: Side, px: str, expected: D | None) -> None:
        assert limit_reference(side, D(px), bar(1, "100", "102", "97", "101")) == expected


class TestValidation:
    def test_a_buy_short_of_cash_is_rejected_and_cash_is_unchanged(self) -> None:
        # 10 * 100 = 1000.00 plus 1.00 fixed = 1001.00 > 1000.00
        state = open_portfolio("1000")
        result = validate_intent(
            market(Side.BUY, 10),
            state,
            session=4,
            last_price=D("100"),
            bar_volume=D("1000000"),
            costs=LinearCostModel(fixed=D("1")),
            slippage=NO_SLIP,
        )
        assert isinstance(result, Rejection)
        assert result.reason is RejectReason.INSUFFICIENT_CASH
        assert result.session == 4
        assert "1001.00" in result.detail
        assert state.cash == D("1000.00")
        assert dict(state.positions) == {}

    def test_a_buy_that_exactly_fits_is_accepted(self) -> None:
        # 9 * 100.05 = 900.45; costs 1.00 + 0.045 -> 0.04 (half even) + 0.450225 -> 0.45 = 1.49
        state = open_portfolio("901.94")
        intent = market(Side.BUY, 9)
        kwargs = {
            "last_price": D("100"),
            "bar_volume": D("1000000"),
            "costs": COSTS,
            "slippage": FIVE_BPS,
        }
        assert required_cash(intent, **kwargs) == D("901.94")  # type: ignore[arg-type]
        assert validate_intent(intent, state, session=0, **kwargs) is None  # type: ignore[arg-type]

    def test_slippage_is_included_in_the_estimate(self) -> None:
        # 10 * 100.05 = 1000.50 > 1000.00
        result = validate_intent(
            market(Side.BUY, 10),
            open_portfolio("1000"),
            session=0,
            last_price=D("100"),
            bar_volume=D("1000000"),
            costs=FREE,
            slippage=FIVE_BPS,
        )
        assert isinstance(result, Rejection)

    def test_a_limit_buy_is_checked_at_its_limit(self) -> None:
        kwargs = {
            "session": 0,
            "last_price": D("50"),
            "bar_volume": D("1000000"),
            "costs": FREE,
            "slippage": FIVE_BPS,
        }
        state = open_portfolio("1000")
        ok = validate_intent(limit(Side.BUY, 10, "100"), state, **kwargs)  # type: ignore[arg-type]
        short = validate_intent(limit(Side.BUY, 10, "100.01"), state, **kwargs)  # type: ignore[arg-type]
        assert ok is None
        assert isinstance(short, Rejection)

    def test_reserved_cash_counts_against_a_buy(self) -> None:
        result = validate_intent(
            market(Side.BUY, 5),
            open_portfolio("1000"),
            session=0,
            last_price=D("100"),
            bar_volume=D("1000000"),
            costs=FREE,
            slippage=NO_SLIP,
            reserved_cash=D("500.01"),
        )
        assert isinstance(result, Rejection)
        assert result.reason is RejectReason.INSUFFICIENT_CASH

    def test_an_oversell_is_rejected_and_the_position_is_unchanged(self) -> None:
        state = holding(5, "100")
        result = validate_intent(
            market(Side.SELL, 6),
            state,
            session=2,
            last_price=D("100"),
            bar_volume=D("1000000"),
            costs=COSTS,
            slippage=FIVE_BPS,
        )
        assert isinstance(result, Rejection)
        assert result.reason is RejectReason.INSUFFICIENT_POSITION
        assert state.positions["AAPL"].quantity == 5
        assert state.cash == D("99500.00")

    def test_selling_a_symbol_not_held_is_rejected(self) -> None:
        result = validate_intent(
            market(Side.SELL, 1, symbol="MSFT"),
            holding(5, "100"),
            session=0,
            last_price=D("100"),
            bar_volume=D("1000000"),
            costs=FREE,
            slippage=NO_SLIP,
        )
        assert isinstance(result, Rejection)
        assert result.reason is RejectReason.INSUFFICIENT_POSITION

    def test_reserved_shares_count_against_a_sale(self) -> None:
        kwargs = {
            "session": 0,
            "last_price": D("100"),
            "bar_volume": D("1000000"),
            "costs": FREE,
            "slippage": NO_SLIP,
        }
        state = holding(5, "100")
        assert validate_intent(market(Side.SELL, 5), state, **kwargs) is None  # type: ignore[arg-type]
        assert isinstance(
            validate_intent(market(Side.SELL, 3), state, reserved_shares=3, **kwargs),  # type: ignore[arg-type]
            Rejection,
        )

    def test_an_oversell_reaching_the_fill_is_rejected(self) -> None:
        result = process_order(
            order(market(Side.SELL, 6)),
            session=1,
            bar=bar(1, "100", "100", "100", "100"),
            state=holding(5, "100"),
            costs=FREE,
            slippage=NO_SLIP,
        )
        assert isinstance(result, Rejection)
        assert result.reason is RejectReason.INSUFFICIENT_POSITION


class TestOrders:
    def test_place_order_sets_the_expiry_session(self) -> None:
        placed = place_order(
            limit(Side.BUY, 1, "10", expires_after=5), order_id="x", seq=3, session=7
        )
        assert placed == Order("x", placed.intent, 3, 7, 12, OrderStatus.OPEN)

    def test_market_orders_take_no_expiry_session(self) -> None:
        assert expiry_session(market(Side.BUY, 1), 3) is None

    def test_refuses_an_order_that_is_not_open(self) -> None:
        done = Order("o1", market(Side.BUY, 1), 1, 0, status=OrderStatus.FILLED)
        with pytest.raises(ValueError, match="not open"):
            process_order(
                done,
                session=1,
                bar=bar(1, "1", "1", "1", "1"),
                state=open_portfolio("10"),
                costs=FREE,
                slippage=NO_SLIP,
            )

    def test_refuses_a_bar_of_another_symbol_or_session(self) -> None:
        for wrong in (bar(1, "1", "1", "1", "1", symbol="MSFT"), bar(2, "1", "1", "1", "1")):
            with pytest.raises(ValueError):
                process_order(
                    order(market(Side.BUY, 1)),
                    session=1,
                    bar=wrong,
                    state=open_portfolio("10"),
                    costs=FREE,
                    slippage=NO_SLIP,
                )
