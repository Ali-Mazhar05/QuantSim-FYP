"""Run metrics served by ``GET /portfolios/{id}/metrics`` (task A16, A-FR-14).

The figures that are plain sums over the projections (trades, costs, sessions, the final
value) are computed here. Return, volatility, Sharpe, max drawdown and turnover come from
the shared metrics library (``qs_quant.metrics``, K6) through a
:class:`MetricsCalculator`; until it is wired in, :class:`PendingMetrics` leaves them
``None`` and the API names them in ``pending``. Replacing the calculator is the only
change K6 needs here.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, fields
from decimal import Decimal
from typing import Protocol

__all__ = [
    "PENDING",
    "MetricsCalculator",
    "PendingMetrics",
    "RunFigures",
    "SeriesMetrics",
]


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
