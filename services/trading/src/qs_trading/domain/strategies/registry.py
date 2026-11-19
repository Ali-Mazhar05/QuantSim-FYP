"""The built-in strategy kinds (task A12, A-FR-01; ADR 05).

A strategy is stored as ``kind`` plus ``params`` JSONB. :data:`PARAMS` maps each kind to
its parameter model, which the API validates against (a ``ValidationError`` naming the
field becomes a 422); :data:`REGISTRY` maps each kind to the factory the engine builds the
strategy with.
"""

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

from qs_trading.domain.strategies.buy_and_hold import BuyAndHold, BuyAndHoldParams
from qs_trading.domain.strategies.ma_crossover import MaCrossover, MaCrossoverParams
from qs_trading.domain.strategies.mean_reversion import MeanReversion, MeanReversionParams
from qs_trading.domain.strategies.momentum import Momentum, MomentumParams
from qs_trading.domain.strategies.params import StrategyParams
from qs_trading.domain.strategy import Strategy, StrategyFactory

__all__ = [
    "KINDS",
    "PARAMS",
    "REGISTRY",
    "UnknownStrategyKind",
    "build_strategy",
    "params_model",
    "validate_params",
]


class UnknownStrategyKind(KeyError):
    """A ``kind`` that is not one of the built-in strategies."""


PARAMS: Mapping[str, type[StrategyParams]] = MappingProxyType(
    {
        model.kind: model
        for model in (BuyAndHoldParams, MaCrossoverParams, MomentumParams, MeanReversionParams)
    }
)

REGISTRY: Mapping[str, StrategyFactory] = MappingProxyType(
    {
        BuyAndHold.kind: BuyAndHold.from_params,
        MaCrossover.kind: MaCrossover.from_params,
        Momentum.kind: Momentum.from_params,
        MeanReversion.kind: MeanReversion.from_params,
    }
)

KINDS: tuple[str, ...] = tuple(REGISTRY)


def params_model(kind: str) -> type[StrategyParams]:
    """The parameter model of ``kind``."""
    try:
        return PARAMS[kind]
    except KeyError:
        raise UnknownStrategyKind(kind) from None


def validate_params(kind: str, params: Mapping[str, Any]) -> StrategyParams:
    """Validated parameters of ``kind``, with defaults filled in. Raises
    ``pydantic.ValidationError`` naming the field when one is wrong."""
    return params_model(kind).model_validate(params)


def build_strategy(kind: str, params: Mapping[str, Any]) -> Strategy:
    """The strategy of ``kind`` built from ``params`` (validated on the way)."""
    try:
        factory = REGISTRY[kind]
    except KeyError:
        raise UnknownStrategyKind(kind) from None
    return factory(params)
