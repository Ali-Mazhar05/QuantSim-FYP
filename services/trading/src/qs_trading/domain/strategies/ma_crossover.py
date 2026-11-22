"""Moving-average crossover (task A12, A-FR-01).

For each symbol, the fast and slow simple moving averages of the last ``fast`` and ``slow``
closes up to ``t``. The position follows the regime: long while the fast average is above
the slow one, flat while it is below; when they are equal nothing changes. So the strategy
buys when the fast average crosses above the slow one and sells the whole holding when it
crosses below.

* **Warm-up.** A symbol needs ``slow`` bars, and a bar at ``t`` itself, before it gives a
  signal; until then, and on a session it has no bar, it is left alone. A symbol that is
  already above its slow average when the warm-up ends is bought then.
* **Sizing.** Each symbol has an equal slot of ``1 / len(symbols)`` of investable value;
  an entry buys ``floor(slot / close)`` shares. A held position is not topped up.
* **No state.** The signal is read from the view alone, so a rejected entry is retried at
  the next session and a resumed engine places the same orders (A-FR-13).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, localcontext
from typing import Annotated, Any, ClassVar

from pydantic import Field, ValidationInfo, field_validator

from qs_trading.domain.orders import OrderIntent
from qs_trading.domain.strategies.params import StrategyParams
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

KIND = "ma_crossover"
MAX_WINDOW = 1000


class MaCrossoverParams(StrategyParams):
    kind: ClassVar[str] = KIND

    fast: Annotated[int, Field(ge=1, le=MAX_WINDOW)] = 20
    slow: Annotated[int, Field(ge=2, le=MAX_WINDOW)] = 50

    @field_validator("slow")
    @classmethod
    def _slow_above_fast(cls, value: int, info: ValidationInfo) -> int:
        fast = info.data.get("fast")
        if fast is not None and value <= fast:
            raise ValueError(f"slow must be greater than fast ({fast})")
        return value


@dataclass(frozen=True, slots=True)
class MaCrossover:
    kind: ClassVar[str] = KIND

    params: MaCrossoverParams

    @classmethod
    def from_params(cls, params: Mapping[str, Any]) -> "MaCrossover":
        return cls(MaCrossoverParams.model_validate(params))

    def signal(self, view: HistoryView, symbol: str) -> int | None:
        """``1`` long, ``-1`` flat, ``0`` no change; ``None`` before the warm-up ends or
        when ``symbol`` has no bar at ``t``."""
        bars = view.bars(symbol, self.params.slow)
        if len(bars) < self.params.slow or bars[-1].session != view.session:
            return None
        closes = [b.close for b in bars]
        with localcontext(DECIMAL_CONTEXT):
            slow = sum(closes, Decimal(0)) / self.params.slow
            fast = sum(closes[-self.params.fast :], Decimal(0)) / self.params.fast
        return 1 if fast > slow else -1 if fast < slow else 0

    def on_bar(self, view: HistoryView) -> Sequence[OrderIntent]:
        if not view.symbols:
            return ()
        closes = latest_closes(view)
        value = portfolio_value(view, closes)
        with localcontext(DECIMAL_CONTEXT):
            slot = investable(value, self.params.cash_buffer) / len(view.symbols)
        targets: dict[str, int] = {}
        for symbol in view.symbols:
            signal = self.signal(view, symbol)
            holding = held(view, symbol)
            if signal == 1 and holding == 0:
                targets[symbol] = whole_shares(slot, closes[symbol])
            elif signal == -1 and holding > 0:
                targets[symbol] = 0
        return orders_toward(view, targets, closes, value, self.params.cash_buffer)
