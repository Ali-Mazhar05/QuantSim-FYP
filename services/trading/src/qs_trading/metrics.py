"""Run metrics served by ``GET /portfolios/{id}/metrics`` and stored in
``portfolio_metrics`` when a run completes (task A16, A-FR-14).

The figures that are plain sums over the projections (trades, costs, sessions, the final
value) are computed here. Return, volatility, Sharpe, max drawdown and turnover come from
the shared metrics library (``qs_quant.metrics``, K6) through a
:class:`MetricsCalculator`: :data:`QUANT_METRICS` in the service, :data:`PENDING` (which
computes nothing) where a test wants the ratios left out. A ratio the library leaves
undefined stays ``None`` and the API names it in ``pending``.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, fields
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Protocol

import qs_quant
from qs_quant import metrics as k6

__all__ = [
    "PENDING",
    "QUANT_METRICS",
    "RATIO_LIMIT",
    "RATIO_PLACES",
    "MetricsCalculator",
    "PendingMetrics",
    "QuantMetrics",
    "RunFigures",
    "SeriesMetrics",
    "to_ratio",
]

RATIO_PLACES = Decimal("1e-12")
"""``portfolio_metrics`` ratio columns are ``Numeric(20, 12)``."""

RATIO_LIMIT = Decimal("1e8")
"""``Numeric(20, 12)`` holds ``|x| < 1e8``; a larger ratio carries no meaning (a Sharpe
ratio of a near-constant series) and is left ``None`` rather than failing the write."""


@dataclass(frozen=True, slots=True)
class RunFigures:
    """What a portfolio's metrics are computed from, read from its projections."""

    portfolio_id: uuid.UUID
    initial_capital: Decimal
    values: Sequence[Decimal]  # portfolio value at each valued session, ascending
    trades: int  # fills
    total_costs: Decimal  # sum of cost_total over the fills
    traded_notional: Decimal  # sum of fill_price * quantity over the fills
    final_seq: int
    final_hash: str | None

    @property
    def sessions(self) -> int:
        return len(self.values)

    @property
    def final_value(self) -> Decimal | None:
        return self.values[-1] if self.values else None


@dataclass(frozen=True, slots=True)
class SeriesMetrics:
    """The metrics of the value series; ``None`` is a metric not computed."""

    total_return: Decimal | None = None
    volatility: Decimal | None = None
    sharpe: Decimal | None = None
    max_drawdown: Decimal | None = None
    turnover: Decimal | None = None

    def pending(self) -> list[str]:
        """The names of the metrics not computed, in field order."""
        return [f.name for f in fields(self) if getattr(self, f.name) is None]


class MetricsCalculator(Protocol):
    def series_metrics(self, figures: RunFigures) -> SeriesMetrics:
        """The metrics of ``figures``; ``Decimal`` results (the library works in float)."""
        ...


class PendingMetrics:
    """Computes nothing: the metrics library is not available yet."""

    def series_metrics(self, figures: RunFigures) -> SeriesMetrics:
        return SeriesMetrics()


PENDING = PendingMetrics()


def to_ratio(x: float | None) -> Decimal | None:
    """A K6 float as a stored ratio: ``Decimal(repr(x))`` rounded half-even to 12 places,
    or ``None`` when undefined or too large for the column."""
    if x is None:
        return None
    value = Decimal(repr(x)).quantize(RATIO_PLACES, rounding=ROUND_HALF_EVEN)
    return None if abs(value) >= RATIO_LIMIT else value


class QuantMetrics:
    """Run metrics from the shared metrics library (K6).

    The series is the initial capital followed by the value at each valued session, so
    the first session's costs and moves count and total return is final / initial - 1.
    Turnover is the traded notional over the mean of that series. A value of exactly 0
    (everything lost) has no simple return after it, so volatility and Sharpe are then
    left undefined while return, drawdown and turnover are still computed.
    """

    version = qs_quant.__version__

    def series_metrics(self, figures: RunFigures) -> SeriesMetrics:
        if not figures.values:
            return SeriesMetrics()
        values = [figures.initial_capital, *figures.values]
        try:
            returns = k6.simple_returns(values)
        except ValueError:
            volatility = sharpe = None
        else:
            volatility = k6.annualised_volatility(returns)
            sharpe = k6.sharpe(returns)
        return SeriesMetrics(
            total_return=to_ratio(k6.total_return(values)),
            volatility=to_ratio(volatility),
            sharpe=to_ratio(sharpe),
            max_drawdown=to_ratio(k6.max_drawdown(values)),
            turnover=to_ratio(k6.turnover([figures.traded_notional], values)),
        )


QUANT_METRICS = QuantMetrics()
