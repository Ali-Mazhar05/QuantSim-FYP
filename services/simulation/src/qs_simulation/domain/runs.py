"""A Monte Carlo run as pure values and functions (B16).

Everything a run decides without touching a database or a service: the storage rule, the start
price and parameter arrays a generator needs, the statistics of the terminal prices, the per-step
quantiles, the median path and the conversion of floats to the decimals that are stored. The job
(``qs_simulation.runs``) wires these to the ports and to the tables.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

import numpy as np

from qs_simulation.domain.correlation import Array
from qs_simulation.ports import RiskCalculator

MIN_PATHS = 20  # the risk statistics need at least this many returns (Lane C, 7.6)
MAX_INSTRUMENTS = 40  # the demo universe; the correlation matrix is this wide at most
FULL_STORAGE_MAX_INSTRUMENTS = 10  # DL-013
FULL_STORAGE_MAX_VALUES = 252_000  # paths x steps per instrument (DL-013)
QUANTILE_LEVELS = (0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99)
ALPHA = 0.95

PRICE_PLACES = 10  # NUMERIC(23, 10), as market's adjusted prices
STATISTIC_PLACES = 12  # NUMERIC(28, 12)
SMALLEST_PRICE = Decimal(1).scaleb(-PRICE_PLACES)
LARGEST_PRICE = Decimal(10) ** 13  # NUMERIC(23, 10) holds below this

StorageMode = Literal["full", "quantiles"]

CORRELATION_UNAVAILABLE = "correlation_unavailable"
UNSTORABLE_PATHS = "unstorable_paths"
NO_START_PRICE = "no_start_price"
INVALID_WINDOW = "invalid_correlation_window"


class RunRefused(Exception):
    """The run cannot be made from this data. Asking again gives the same answer, so the job is
    not retried: the run is marked failed with the reason."""

    def __init__(self, code: str, reason: str) -> None:
        self.code = code
        self.reason = reason
        super().__init__(reason)


def run_values(n_paths: int, n_steps: int, n_instruments: int) -> int:
    """How many prices a run holds in memory while it is generated."""
    return n_paths * n_steps * n_instruments


def storage_mode(n_paths: int, n_steps: int, n_instruments: int) -> StorageMode:
    """Every value is stored when a run is small enough, else the seed and per-step quantiles are
    (ADR 03, DL-013): at most 252,000 values per instrument and at most 10 instruments."""
    small = n_paths * n_steps <= FULL_STORAGE_MAX_VALUES
    return "full" if small and n_instruments <= FULL_STORAGE_MAX_INSTRUMENTS else "quantiles"


def to_price(value: float) -> Decimal:
    """A generated price as the decimal that is stored and served (10 places). A price that does not
    fit the column, or rounds to zero, refuses the run instead of failing in the database."""
    if not np.isfinite(value):
        raise RunRefused(UNSTORABLE_PATHS, "a generated price is not a finite number")
    price = Decimal(f"{value:.{PRICE_PLACES}f}")
    if price < SMALLEST_PRICE or price >= LARGEST_PRICE:
        raise RunRefused(
            UNSTORABLE_PATHS, f"a generated price ({price}) is outside the storable range"
        )
    return price


def to_statistic(value: float) -> Decimal:
    if not np.isfinite(value):
        raise RunRefused(UNSTORABLE_PATHS, "a statistic is not a finite number")
    return Decimal(f"{value:.{STATISTIC_PLACES}f}")


def check_paths(paths: Array) -> None:
    """Every generated price must be storable; checked once, on the whole array."""
    if not np.all(np.isfinite(paths)):
        raise RunRefused(UNSTORABLE_PATHS, "a generated price is not a finite number")
    low, high = float(paths.min()), float(paths.max())
    if low < float(SMALLEST_PRICE) or high >= float(LARGEST_PRICE):
        raise RunRefused(
            UNSTORABLE_PATHS,
            f"generated prices range from {low:g} to {high:g}, outside what can be stored",
        )


@dataclass(frozen=True)
class InstrumentSummary:
    """Statistics of one instrument's terminal prices over all paths."""

    mean_price: Decimal
    median_price: Decimal
    p5_price: Decimal
    p95_price: Decimal
    var95: Decimal
    cvar95: Decimal


def terminal_statistics(paths: Array, s0: Array, risk: RiskCalculator) -> list[InstrumentSummary]:
    """Mean, median, 5th and 95th percentile of S_T per instrument, and VaR and CVaR at 95 percent
    of the returns ``R = S_T / S_0 - 1`` (losses are positive fractions of the start price)."""
    terminal = paths[:, -1, :]
    summaries: list[InstrumentSummary] = []
    for i in range(terminal.shape[1]):
        prices = terminal[:, i]
        value_at_risk, expected_shortfall = risk.var_cvar(prices / s0[i] - 1.0, ALPHA)
        p5, p95 = np.percentile(prices, [5, 95])
        summaries.append(
            InstrumentSummary(
                mean_price=to_price(float(prices.mean())),
                median_price=to_price(float(np.median(prices))),
                p5_price=to_price(float(p5)),
                p95_price=to_price(float(p95)),
                var95=to_statistic(value_at_risk),
                cvar95=to_statistic(expected_shortfall),
            )
        )
    return summaries


def step_quantiles(paths: Array) -> Array:
    """Quantiles across paths at every step: shape (steps, instruments, 7), at QUANTILE_LEVELS."""
    levels = np.quantile(paths, QUANTILE_LEVELS, axis=0)  # (7, steps, instruments)
    result: Array = np.moveaxis(levels, 0, -1)
    return result


def median_path_index(paths: Array, s0: Array) -> int:
    """The path a portfolio binds to (DL-001): rank paths by the terminal value of the basket of
    equal-weighted normalised prices, ``mean_i(S_T / S_0)``, take the lower median, and among the
    paths with exactly that value the lowest index."""
    values = (paths[:, -1, :] / s0).mean(axis=1)
    rank = (values.shape[0] - 1) // 2
    median = np.partition(values, rank)[rank]
    return int(np.flatnonzero(values == median).min())
