"""Cross-sectional momentum under a max-position cap (task A12, A-FR-01, A-FR-03).

* **Score.** A symbol's momentum at ``t`` is ``close_t / close_(t - lookback) - 1`` over its
  own last ``lookback + 1`` bars. A symbol is eligible only when it has that many bars and a
  bar at ``t`` itself.
* **Schedule.** The first rebalance is at session ``lookback`` (the end of the warm-up),
  then every ``rebalance_every`` sessions: ``t >= lookback`` and
  ``(t - lookback) % rebalance_every == 0``. The schedule depends on ``t`` alone, so a
  resumed engine rebalances on the same sessions (A-FR-13).
* **Selection.** The ``top_n`` eligible symbols by score, highest first; ties go to the
  symbol earlier in the environment's order.
* **Weights.** Each selected symbol targets ``min(1 / top_n, max_position)`` of investable
  value; the rest stays in cash, also when fewer than ``top_n`` symbols are eligible.
  Every other symbol targets zero, so a rebalance sells what dropped out, trims what grew
  past its target and tops up what fell below it.
* **Cap between rebalances (A-FR-03).** At every other session, a position worth more than
  ``max_position`` of portfolio value is trimmed back to ``max_position`` of investable
  value. Trimming waits until the cap itself is crossed, so the cash buffer works as a band
  and small moves do not trade.

What the cap guarantees: once the orders fill at the prices they were sized at, every
position is worth at most ``max_position`` of portfolio value, with costs up to the cash
buffer. A gap between the close at ``t`` and the open at ``t + 1`` can move a holding over
the cap; the next session trims it.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, localcontext
from typing import Annotated, Any, ClassVar

from pydantic import Field

from qs_trading.domain.orders import OrderIntent
from qs_trading.domain.strategies.params import Fraction, StrategyParams
from qs_trading.domain.strategies.sizing import (
    DECIMAL_CONTEXT,
    investable,
    latest_closes,
    orders_toward,
    portfolio_value,
    whole_shares,
)
from qs_trading.domain.strategy import HistoryView

KIND = "momentum"
MAX_LOOKBACK = 1000


class MomentumParams(StrategyParams):
    kind: ClassVar[str] = KIND

    lookback: Annotated[int, Field(ge=1, le=MAX_LOOKBACK)] = 60
    top_n: Annotated[int, Field(ge=1, le=500)] = 3
    rebalance_every: Annotated[int, Field(ge=1, le=MAX_LOOKBACK)] = 20
    max_position: Annotated[Fraction, Field(gt=0, le=1)] = Decimal("0.25")


@dataclass(frozen=True, slots=True)
class Momentum:
    kind: ClassVar[str] = KIND

    params: MomentumParams

    @classmethod
    def from_params(cls, params: Mapping[str, Any]) -> "Momentum":
        return cls(MomentumParams.model_validate(params))

    def is_rebalance(self, session: int) -> bool:
        lookback = self.params.lookback
        return session >= lookback and (session - lookback) % self.params.rebalance_every == 0

    def score(self, view: HistoryView, symbol: str) -> Decimal | None:
        """Return over the lookback; ``None`` when ``symbol`` is not eligible at ``t``."""
        bars = view.bars(symbol, self.params.lookback + 1)
        if len(bars) <= self.params.lookback or bars[-1].session != view.session:
            return None
        with localcontext(DECIMAL_CONTEXT):
            return bars[-1].close / bars[0].close - 1

    def selection(self, view: HistoryView) -> list[str]:
        """The symbols to hold after a rebalance at ``t``, best first."""
        scored = [
            (score, index, symbol)
            for index, symbol in enumerate(view.symbols)
            if (score := self.score(view, symbol)) is not None
        ]
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [symbol for _, _, symbol in scored[: self.params.top_n]]

    def on_bar(self, view: HistoryView) -> Sequence[OrderIntent]:
        closes = latest_closes(view)
        value = portfolio_value(view, closes)
        capital = investable(value, self.params.cash_buffer)
        cap = self.params.max_position
        targets: dict[str, int] = {}
        with localcontext(DECIMAL_CONTEXT):
            if self.is_rebalance(view.session):
                weight = min(Decimal(1) / self.params.top_n, cap)
                chosen = set(self.selection(view))
                for symbol in view.symbols:
                    if symbol not in closes:
                        continue
                    if symbol in chosen:
                        targets[symbol] = whole_shares(weight * capital, closes[symbol])
                    else:
                        targets[symbol] = 0
            else:
                for symbol, position in view.portfolio.positions.items():
                    close = closes.get(symbol)
                    if close is not None and position.quantity * close > cap * value:
                        targets[symbol] = whole_shares(cap * capital, close)
        return orders_toward(view, targets, closes, value, self.params.cash_buffer)
