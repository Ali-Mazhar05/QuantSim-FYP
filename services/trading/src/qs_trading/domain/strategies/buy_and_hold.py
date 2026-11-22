"""Buy and hold (task A12, A-FR-01).

Buys every target symbol once and never sells. Targets are the environment's symbols at
equal weights, or the given ``weights`` (fractions of investable value, summing to at most
one; symbols outside the environment are ignored).

The strategy keeps no state between sessions: at each session it buys the targets it does
not hold yet. In a normal run that is once, at the first session; a buy that was rejected or
had no price yet is retried at the next session, and a crash-resumed engine places exactly
the orders an uninterrupted one would (A-FR-13).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, localcontext
from typing import Annotated, Any, ClassVar

from pydantic import Field, field_validator

from qs_trading.domain.orders import OrderIntent
from qs_trading.domain.strategies.params import Fraction, StrategyParams
from qs_trading.domain.strategies.sizing import (
    DECIMAL_CONTEXT,
    held,
    investable,
    latest_closes,
    orders_toward,
    portfolio_value,
    whole_shares,
)
from qs_trading.domain.strategy import HistoryView

KIND = "buy_and_hold"


class BuyAndHoldParams(StrategyParams):
    kind: ClassVar[str] = KIND

    weights: (
        dict[
            Annotated[str, Field(min_length=1, max_length=32)],
            Annotated[Fraction, Field(gt=0, le=1)],
        ]
        | None
    ) = None
    """Fraction of investable value per symbol; ``None`` means equal weights."""

    @field_validator("weights")
    @classmethod
    def _weights_sum_to_at_most_one(
        cls, value: dict[str, Decimal] | None
    ) -> dict[str, Decimal] | None:
        if value is None:
            return None
        if not value:
            raise ValueError("give at least one weight, or leave weights out for equal weights")
        if sum(value.values(), Decimal(0)) > 1:
            raise ValueError("weights must sum to at most 1")
        return value


@dataclass(frozen=True, slots=True)
class BuyAndHold:
    kind: ClassVar[str] = KIND

    params: BuyAndHoldParams

    @classmethod
    def from_params(cls, params: Mapping[str, Any]) -> "BuyAndHold":
        return cls(BuyAndHoldParams.model_validate(params))

    def weights(self, symbols: Sequence[str]) -> dict[str, Decimal]:
        """Target weight per environment symbol."""
        if self.params.weights is None:
            if not symbols:
                return {}
            with localcontext(DECIMAL_CONTEXT):
                equal = Decimal(1) / len(symbols)
            return dict.fromkeys(symbols, equal)
        return {s: self.params.weights[s] for s in symbols if s in self.params.weights}

    def on_bar(self, view: HistoryView) -> Sequence[OrderIntent]:
        closes = latest_closes(view)
        value = portfolio_value(view, closes)
        capital = investable(value, self.params.cash_buffer)
        targets: dict[str, int] = {}
        with localcontext(DECIMAL_CONTEXT):
            for symbol, weight in self.weights(view.symbols).items():
                if held(view, symbol) == 0 and symbol in closes:
                    targets[symbol] = whole_shares(weight * capital, closes[symbol])
        return orders_toward(view, targets, closes, value, self.params.cash_buffer)
