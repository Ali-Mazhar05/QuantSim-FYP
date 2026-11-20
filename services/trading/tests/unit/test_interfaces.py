"""Checks on the frozen engine interfaces (Wave 0): validation rules and event round trips."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from qs_trading.domain.accounting import Fill, Side
from qs_trading.domain.costs import CostBreakdown
from qs_trading.domain.events import (
    PAYLOADS,
    EventType,
    OrderFilledV1,
    OrderRejectedV1,
    RunStartedV1,
)
from qs_trading.domain.orders import Execution, OrderIntent, OrderType, RejectReason
from qs_trading.ports.market_environment import EnvironmentRef


class TestOrderIntent:
    def test_market_order_defaults(self) -> None:
        intent = OrderIntent("AAPL", Side.BUY, 10)
        assert intent.order_type is OrderType.MARKET
        assert intent.limit_price is None

    def test_limit_order_rounds_its_price(self) -> None:
        # Plain strings from JSON are coerced to the enums
        intent = OrderIntent("AAPL", "buy", 5, "limit", Decimal("101.123456789"), 3)  # type: ignore[arg-type]
        assert intent.side is Side.BUY
        assert intent.limit_price == Decimal("101.12345679")

    @pytest.mark.parametrize(
        ("kwargs", "error"),
        [
            ({"quantity": 0}, ValueError),
            ({"quantity": -1}, ValueError),
            ({"quantity": 1.5}, TypeError),
            ({"quantity": True}, TypeError),
            ({"symbol": ""}, ValueError),
            ({"order_type": OrderType.LIMIT}, ValueError),
            ({"limit_price": Decimal("10")}, ValueError),
            ({"expires_after": 2}, ValueError),
            (
                {"order_type": OrderType.LIMIT, "limit_price": Decimal("10"), "expires_after": 0},
                ValueError,
            ),
        ],
    )
    def test_refuses_invalid(self, kwargs: dict[str, object], error: type[Exception]) -> None:
        base: dict[str, object] = {"symbol": "AAPL", "side": Side.BUY, "quantity": 1}
        with pytest.raises(error):
            OrderIntent(**(base | kwargs))  # type: ignore[arg-type]


class TestCostBreakdown:
    def test_total_is_the_sum_of_rounded_parts(self) -> None:
        costs = CostBreakdown(Decimal("1"), Decimal("0.005"), Decimal("0.125"))
        assert costs.per_share == Decimal("0.00")  # half to even
        assert costs.percentage == Decimal("0.12")
        assert costs.total == Decimal("1.12")

    def test_refuses_negative(self) -> None:
        with pytest.raises(ValueError):
            CostBreakdown(fixed=Decimal("-0.01"))

    def test_execution_cost_must_match_fill(self) -> None:
        costs = CostBreakdown(fixed=Decimal("1"))
        fill = Fill("AAPL", Side.BUY, 1, Decimal("100"), Decimal("2"))
        with pytest.raises(ValueError):
            Execution("o1", 1, Decimal("100"), Decimal("0"), costs, fill)


class TestEnvironmentRef:
    def test_replay_takes_no_path(self) -> None:
        with pytest.raises(ValueError):
            EnvironmentRef("replay", "env-1", path_index=0)

    def test_simulation_needs_a_path(self) -> None:
        with pytest.raises(ValueError):
            EnvironmentRef("simulation", "run-1")
        assert EnvironmentRef("simulation", "run-1", 3).path_index == 3


class TestEvents:
    def test_every_type_has_a_v1_payload(self) -> None:
        assert {key for key in PAYLOADS} == {(t, 1) for t in EventType}

    def test_money_round_trips_through_json_exactly(self) -> None:
        event = OrderFilledV1(
            order_id="o1",
            session=4,
            symbol="AAPL",
            side=Side.BUY,
            quantity=10,
            reference_price=Decimal("100.00000000"),
            fill_price=Decimal("100.05000000"),
            slippage=Decimal("0.05000000"),
            cost_fixed=Decimal("1.00"),
            cost_per_share=Decimal("0.05"),
            cost_percentage=Decimal("0.10"),
            cost_total=Decimal("1.15"),
            cash_after=Decimal("98998.35"),
        )
        data = event.model_dump(mode="json")
        assert data["fill_price"] == "100.05000000"
        assert data["side"] == "buy"
        assert OrderFilledV1.model_validate(data) == event

    def test_payloads_are_immutable_and_strict(self) -> None:
        rejected = OrderRejectedV1(
            session=1,
            symbol="AAPL",
            side=Side.BUY,
            quantity=1,
            order_type=OrderType.MARKET,
            reason=RejectReason.INSUFFICIENT_CASH,
        )
        with pytest.raises(ValidationError):
            rejected.session = 2  # type: ignore[misc]
        with pytest.raises(ValidationError):
            OrderRejectedV1.model_validate(rejected.model_dump() | {"extra": 1})

    def test_run_started_records_the_source(self) -> None:
        started = RunStartedV1(
            strategy_kind="buy_and_hold",
            strategy_params={},
            initial_capital=Decimal("100000.00"),
            cost_model={"fixed": "1.00"},
            slippage_model={"kind": "fixed_bps", "bps": "5"},
            env_type="replay",
            env_id="env-1",
            source_fingerprint="abc123",
        )
        assert started.type is EventType.RUN_STARTED
        assert started.version == 1
        assert started.path_index is None

    def test_tick_event_carries_its_session_close(self) -> None:
        tick = PAYLOADS[(EventType.TICK, 1)].model_validate(
            {
                "session": 0,
                "ts": datetime(2026, 1, 2, 21, tzinfo=UTC),
                "first_tick_seq": 1,
                "last_tick_seq": 2,
            }
        )
        assert tick.model_dump(mode="json")["ts"] == "2026-01-02T21:00:00Z"
