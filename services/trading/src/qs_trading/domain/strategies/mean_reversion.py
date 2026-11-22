"""Mean reversion on a z-score (task A12, A-FR-01).

For each symbol, ``z = (close_t - mean) / std`` over the last ``window`` closes up to and
including ``t`` (population standard deviation). A flat symbol is bought when
``z <= -entry_z`` (well below its mean); a held one is sold in full when ``z >= exit_z``
(back to, or past, the exit level). Between the two levels nothing changes, and
``exit_z > -entry_z`` keeps the two levels apart.

* **Warm-up.** A symbol needs ``window`` bars, and a bar at ``t`` itself, before it gives a
  signal. A window with zero spread gives no signal.
* **Sizing.** As for the moving-average crossover: an equal slot of
  ``1 / len(symbols)`` of investable value per symbol, ``floor(slot / close)`` shares, no
  top-ups.
* **No state.** Signals come from the view alone (A-FR-13).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, localcontext
from typing import Annotated, Any, ClassVar

from pydantic import Field, ValidationInfo, field_validator

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

KIND = "mean_reversion"
MAX_WINDOW = 1000
MAX_Z = Decimal(10)


class MeanReversionParams(StrategyParams):
    kind: ClassVar[str] = KIND

    window: Annotated[int, Field(ge=2, le=MAX_WINDOW)] = 20
    entry_z: Annotated[Fraction, Field(gt=0, le=MAX_Z)] = Decimal(2)
    exit_z: Annotated[Fraction, Field(ge=-MAX_Z, le=MAX_Z)] = Decimal(0)

    @field_validator("exit_z")
    @classmethod
    def _exit_above_entry(cls, value: Decimal, info: ValidationInfo) -> Decimal:
        entry = info.data.get("entry_z")
        if entry is not None and value <= -entry:
            raise ValueError(f"exit_z must be greater than -entry_z ({-entry})")
        return value


@dataclass(frozen=True, slots=True)
class MeanReversion:
    kind: ClassVar[str] = KIND

    params: MeanReversionParams

    @classmethod
    def from_params(cls, params: Mapping[str, Any]) -> "MeanReversion":
        return cls(MeanReversionParams.model_validate(params))

    def zscore(self, view: HistoryView, symbol: str) -> Decimal | None:
        """The z-score of the close at ``t``; ``None`` before the warm-up ends, without a
        bar at ``t``, or when the window has no spread."""
        bars = view.bars(symbol, self.params.window)
        if len(bars) < self.params.window or bars[-1].session != view.session:
            return None
        closes = [b.close for b in bars]
        with localcontext(DECIMAL_CONTEXT):
            mean = sum(closes, Decimal(0)) / len(closes)
            variance = sum(((c - mean) ** 2 for c in closes), Decimal(0)) / len(closes)
            if variance == 0:
                return None
            return (closes[-1] - mean) / variance.sqrt()

    def on_bar(self, view: HistoryView) -> Sequence[OrderIntent]:
        if not view.symbols:
            return ()
        closes = latest_closes(view)
        value = portfolio_value(view, closes)
        with localcontext(DECIMAL_CONTEXT):
            slot = investable(value, self.params.cash_buffer) / len(view.symbols)
        targets: dict[str, int] = {}
        for symbol in view.symbols:
            z = self.zscore(view, symbol)
            if z is None:
                continue
            holding = held(view, symbol)
            if holding == 0 and z <= -self.params.entry_z:
                targets[symbol] = whole_shares(slot, closes[symbol])
            elif holding > 0 and z >= self.params.exit_z:
                targets[symbol] = 0
        return orders_toward(view, targets, closes, value, self.params.cash_buffer)
