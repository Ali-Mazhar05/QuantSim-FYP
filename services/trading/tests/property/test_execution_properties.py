"""Properties of the execution rules over random orders and bars (A11 acceptance).

An execution the module returns is always one the books accept, so cash is never negative
after an accepted buy; slippage never favours the trader; a limit fill is never worse than
its limit; costs are never negative and their total is the sum of the parts.
"""

from datetime import UTC, datetime
from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from qs_trading.domain.accounting import (
    AccountingError,
    Fill,
    PortfolioState,
    Side,
    apply_fill,
    open_portfolio,
)
from qs_trading.domain.costs import LinearCostModel
from qs_trading.domain.execution import place_order, process_order, validate_intent
from qs_trading.domain.orders import Execution, OrderIntent, OrderType, Rejection
from qs_trading.domain.slippage import FixedBpsSlippage, VolumeSlippage
from qs_trading.domain.strategy import Bar

T0 = datetime(2026, 1, 2, 21, tzinfo=UTC)

prices = st.decimals(min_value="0.01", max_value="5000", places=8)
quantities = st.integers(min_value=1, max_value=5000)
volumes = st.decimals(min_value="0", max_value="10000000", places=0)
bps = st.decimals(min_value="0", max_value="500", places=2)
cost_models = st.builds(
    LinearCostModel,
    fixed=st.decimals(min_value="0", max_value="20", places=2),
    per_share=st.decimals(min_value="0", max_value="0.05", places=4),
    pct=st.decimals(min_value="0", max_value="0.01", places=5),
)
slippage_models = st.one_of(
    st.builds(FixedBpsSlippage, bps=bps), st.builds(VolumeSlippage, bps=bps)
)


@st.composite
def bars(draw: st.DrawFn, session: int = 1) -> Bar:
    a, b, c, d = (draw(prices) for _ in range(4))
    low, high = min(a, b, c, d), max(a, b, c, d)
    return Bar(session, "AAPL", T0, c, high, low, d, draw(volumes))


@st.composite
def intents(draw: st.DrawFn) -> OrderIntent:
    side = draw(st.sampled_from(list(Side)))
    quantity = draw(quantities)
    if draw(st.booleans()):
        return OrderIntent("AAPL", side, quantity)
    return OrderIntent("AAPL", side, quantity, OrderType.LIMIT, draw(prices))


@st.composite
def portfolios(draw: st.DrawFn) -> PortfolioState:
    state = open_portfolio(draw(st.decimals(min_value="100", max_value="1000000", places=2)))
    held = draw(st.integers(min_value=0, max_value=5000))
    if held:
        try:
            state = apply_fill(state, Fill("AAPL", Side.BUY, held, draw(prices)))
        except AccountingError:
            pass
    return state


@settings(max_examples=400, deadline=None)
@given(
    state=portfolios(),
    intent=intents(),
    last=bars(session=0),
    fill_bar=bars(session=1),
    costs=cost_models,
    slippage=slippage_models,
)
def test_an_execution_always_applies_and_cash_stays_non_negative(
    state: PortfolioState,
    intent: OrderIntent,
    last: Bar,
    fill_bar: Bar,
    costs: LinearCostModel,
    slippage: FixedBpsSlippage | VolumeSlippage,
) -> None:
    placed = validate_intent(
        intent,
        state,
        session=0,
        last_price=last.close,
        bar_volume=last.volume,
        costs=costs,
        slippage=slippage,
    )
    if placed is not None:
        assert isinstance(placed, Rejection)
        return
    result = process_order(
        place_order(intent, order_id="o1", seq=1, session=0),
        session=1,
        bar=fill_bar,
        state=state,
        costs=costs,
        slippage=slippage,
    )
    if isinstance(result, Execution):
        after = apply_fill(state, result.fill)
        assert after.cash >= 0
        assert result.fill.cost == result.costs.total
    elif isinstance(result, Rejection):
        assert result.session == 1


@settings(max_examples=300, deadline=None)
@given(state=portfolios(), intent=intents(), costs=cost_models, slippage=slippage_models)
def test_a_limit_buy_accepted_at_placement_never_runs_out_of_cash(
    state: PortfolioState,
    intent: OrderIntent,
    costs: LinearCostModel,
    slippage: FixedBpsSlippage | VolumeSlippage,
) -> None:
    # A limit buy is checked at its limit, the worst it can fill at, so the fill never fails.
    if intent.order_type is not OrderType.LIMIT or intent.side is not Side.BUY:
        return
    assert intent.limit_price is not None
    at = intent.limit_price
    bar = Bar(1, "AAPL", T0, at, at, at, at, Decimal("1"))
    if validate_intent(
        intent,
        state,
        session=0,
        last_price=intent.limit_price,
        bar_volume=Decimal("1"),
        costs=costs,
        slippage=slippage,
    ):
        return
    result = process_order(
        place_order(intent, order_id="o1", seq=1, session=0),
        session=1,
        bar=bar,
        state=state,
        costs=costs,
        slippage=slippage,
    )
    assert isinstance(result, Execution)


@settings(max_examples=400, deadline=None)
@given(
    side=st.sampled_from(list(Side)),
    quantity=quantities,
    reference=prices,
    volume=volumes,
    slippage=slippage_models,
)
def test_slippage_is_never_favourable(
    side: Side,
    quantity: int,
    reference: Decimal,
    volume: Decimal,
    slippage: FixedBpsSlippage | VolumeSlippage,
) -> None:
    filled = slippage.fill_price(side, quantity, reference, volume)
    assert filled > 0
    assert filled == filled.quantize(Decimal("0.00000001"))
    if side is Side.BUY:
        assert filled >= reference
    else:
        assert filled <= reference
    assert abs(filled - reference) <= reference * slippage.bps / 10000 + Decimal("0.00000001")


@settings(max_examples=400, deadline=None)
@given(
    intent=intents(),
    fill_bar=bars(),
    costs=cost_models,
    slippage=slippage_models,
)
def test_fills_are_adverse_to_the_reference_and_respect_the_limit(
    intent: OrderIntent,
    fill_bar: Bar,
    costs: LinearCostModel,
    slippage: FixedBpsSlippage | VolumeSlippage,
) -> None:
    rich = open_portfolio("100000000000")
    state = apply_fill(rich, Fill("AAPL", Side.BUY, 5000, Decimal("0.01")))
    result = process_order(
        place_order(intent, order_id="o1", seq=1, session=0),
        session=1,
        bar=fill_bar,
        state=state,
        costs=costs,
        slippage=slippage,
    )
    if not isinstance(result, Execution):
        assert intent.order_type is OrderType.LIMIT
        return
    filled, reference = result.fill.price, result.reference_price
    assert fill_bar.low <= reference <= fill_bar.high
    assert result.slippage == abs(filled - reference)
    if intent.side is Side.BUY:
        assert filled >= reference
        if intent.limit_price is not None:
            assert filled <= intent.limit_price
    else:
        assert filled <= reference
        if intent.limit_price is not None:
            assert filled >= intent.limit_price


@settings(max_examples=400, deadline=None)
@given(costs=cost_models, quantity=quantities, fill_price=prices)
def test_costs_are_non_negative_and_add_up(
    costs: LinearCostModel, quantity: int, fill_price: Decimal
) -> None:
    breakdown = costs.cost(quantity, fill_price)
    parts = (breakdown.fixed, breakdown.per_share, breakdown.percentage)
    assert all(part >= 0 for part in parts)
    assert all(part == part.quantize(Decimal("0.01")) for part in parts)
    assert breakdown.total == sum(parts)
