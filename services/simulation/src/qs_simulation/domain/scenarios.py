"""Stress scenarios as data (B17, B-FR-15, B-FR-16, DL-043).

A scenario is a row: a ``code``, a ``type`` and its ``params``. Two types exist.

``price_shock``: a one-off fall of ``drop`` (a fraction, above 0 and below 1) in every instrument at
step ``at_step``: from then on every price is multiplied by ``1 - drop``. With
``recovery_steps`` above 0 the fall heals in a straight line: the factor is back to 1 at
``at_step + recovery_steps``.

``vol_multiplier``: the diffusion volatility is ``multiplier`` times its calibrated value for the
steps ``from_step`` to ``to_step``, both included. The shocks of the base run are used again, so the
stressed run differs from its parent only by the stress.

Steps count from 1, the first generated step (tick ``session`` 0 is step 1). The functions here are
pure: no I/O.
"""

from dataclasses import dataclass
from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from qs_simulation.domain.correlation import Array

ScenarioType = Literal["price_shock", "vol_multiplier"]


class PriceShock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    drop: float = Field(gt=0, lt=1, description="The fall, as a fraction of the price: 0.2 is 20%")
    at_step: int = Field(ge=1, description="The step the fall happens at, counting from 1")
    recovery_steps: int = Field(
        default=0, ge=0, description="Steps over which the fall heals; 0 means it stays"
    )


class VolMultiplier(BaseModel):
    model_config = ConfigDict(extra="forbid")

    multiplier: float = Field(ge=1, le=10, description="How many times the volatility is raised")
    from_step: int = Field(ge=1, description="First stressed step, counting from 1")
    to_step: int = Field(ge=1, description="Last stressed step")

    @model_validator(mode="after")
    def _ordered(self) -> "VolMultiplier":
        if self.to_step < self.from_step:
            raise ValueError("to_step must not be before from_step")
        return self


@dataclass(frozen=True)
class Scenario:
    type: ScenarioType
    shock: PriceShock | None = None
    vol: VolMultiplier | None = None

    def fits(self, n_steps: int) -> list[tuple[str, str]]:
        """What does not fit a run of ``n_steps``: (field, reason) pairs, empty when it all fits."""
        problems: list[tuple[str, str]] = []
        if self.shock is not None and self.shock.at_step > n_steps:
            problems.append(
                (
                    "at_step",
                    f"the run has {n_steps} steps; the shock is at step {self.shock.at_step}",
                )
            )
        if self.vol is not None and self.vol.to_step > n_steps:
            problems.append(
                (
                    "to_step",
                    f"the run has {n_steps} steps; the stress ends at step {self.vol.to_step}",
                )
            )
        return problems


def parse(type_: str, params: dict[str, Any]) -> Scenario:
    """The scenario a row describes. Raises ``ValidationError`` naming the field that is wrong."""
    if type_ == "price_shock":
        return Scenario("price_shock", shock=PriceShock.model_validate(params))
    if type_ == "vol_multiplier":
        return Scenario("vol_multiplier", vol=VolMultiplier.model_validate(params))
    raise ValueError(f"unknown scenario type {type_!r}")


def problems_of(error: ValidationError) -> list[tuple[str, str]]:
    """(field, message) for each wrong parameter, in the order the parameters are declared."""
    return [(".".join(str(p) for p in e["loc"]) or "params", e["msg"]) for e in error.errors()]


def vol_scale(scenario: Scenario | None, n_steps: int) -> Array | None:
    """The volatility multiplier of each step, or None when the scenario leaves volatility alone."""
    if scenario is None or scenario.vol is None:
        return None
    scale = np.ones(n_steps, dtype=np.float64)
    scale[scenario.vol.from_step - 1 : scenario.vol.to_step] = scenario.vol.multiplier
    return scale


def price_factors(scenario: Scenario | None, n_steps: int) -> Array | None:
    """The factor every price is multiplied by at each step, or None for no price shock."""
    if scenario is None or scenario.shock is None:
        return None
    shock = scenario.shock
    steps = np.arange(1, n_steps + 1, dtype=np.float64)
    factors = np.ones(n_steps, dtype=np.float64)
    after = steps >= shock.at_step
    if shock.recovery_steps == 0:
        factors[after] = 1.0 - shock.drop
    else:
        healed = np.clip((steps[after] - shock.at_step) / shock.recovery_steps, 0.0, 1.0)
        factors[after] = 1.0 - shock.drop * (1.0 - healed)
    return factors


def apply_prices(scenario: Scenario | None, paths: Array) -> Array:
    """``paths`` (paths, steps, instruments) with the price shock on; the input is not changed."""
    factors = price_factors(scenario, paths.shape[1])
    if factors is None:
        return paths
    stressed: Array = paths * factors[None, :, None]
    return stressed
