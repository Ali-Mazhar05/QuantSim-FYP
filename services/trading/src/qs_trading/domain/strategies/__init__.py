"""Built-in strategies (task A12): four kinds behind a history-only view (A-FR-01 to 03).

Every strategy is pure: it reads only the :class:`~qs_trading.domain.strategy.HistoryView`
it is given, keeps no state between sessions and uses no clock or randomness, so the same
view always gives the same orders (A-FR-12). Orders are long-only market orders in whole
shares; :mod:`~qs_trading.domain.strategies.sizing` holds the sizing rules they share.
"""

from qs_trading.domain.strategies.buy_and_hold import BuyAndHold, BuyAndHoldParams
from qs_trading.domain.strategies.ma_crossover import MaCrossover, MaCrossoverParams
from qs_trading.domain.strategies.mean_reversion import MeanReversion, MeanReversionParams
from qs_trading.domain.strategies.momentum import Momentum, MomentumParams
from qs_trading.domain.strategies.params import DEFAULT_CASH_BUFFER, StrategyParams
from qs_trading.domain.strategies.registry import (
    KINDS,
    PARAMS,
    REGISTRY,
    UnknownStrategyKind,
    build_strategy,
    params_model,
    validate_params,
)

__all__ = [
    "DEFAULT_CASH_BUFFER",
    "KINDS",
    "PARAMS",
    "REGISTRY",
    "BuyAndHold",
    "BuyAndHoldParams",
    "MaCrossover",
    "MaCrossoverParams",
    "MeanReversion",
    "MeanReversionParams",
    "Momentum",
    "MomentumParams",
    "StrategyParams",
    "UnknownStrategyKind",
    "build_strategy",
    "params_model",
    "validate_params",
]
