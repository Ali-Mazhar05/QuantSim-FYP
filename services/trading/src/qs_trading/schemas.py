"""Request and response bodies of the Trading API (task A16).

Money is an exact decimal string in JSON, never a float (NFR-INT-001): request amounts
may be a decimal string or a whole number, and responses always carry strings with the
stored number of places. Strategy parameters, cost models and slippage models are stored
as JSON objects in the canonical form their domain models dump (decimals as strings,
defaults filled in), and are returned exactly as stored.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from qs_template import ServiceError
from qs_trading.domain.costs import ExactDecimal, LinearCostModel
from qs_trading.domain.slippage import FixedBpsSlippage, SlippageConfig
from qs_trading.domain.strategies import KINDS

__all__ = [
    "EventOut",
    "EventPage",
    "JobStatus",
    "PortfolioCreate",
    "PortfolioOut",
    "RunAccepted",
    "RunOut",
    "StrategyIn",
    "StrategyOut",
    "money_text",
    "not_found",
    "validation_problem",
]

JobStatus = Literal["queued", "running", "succeeded", "failed"]
EnvType = Literal["replay", "simulation"]

Name = Annotated[str, Field(min_length=1, max_length=120)]
Capital = Annotated[
    ExactDecimal,
    Field(
        gt=0,
        max_digits=20,
        decimal_places=2,
        description="Decimal string (or whole number) in USD, at most 2 decimal places",
    ),
]


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class StrategyIn(_Body):
    """Create or replace a strategy. ``params`` is checked against the parameter model of
    ``kind``; a wrong value gives a 422 whose error location names the field."""

    name: Name
    kind: str = Field(description=f"One of {', '.join(KINDS)}")
    params: dict[str, Any] = Field(
        default_factory=dict, description="Parameters of the kind; omitted ones take defaults"
    )


class StrategyOut(BaseModel):
    id: uuid.UUID
    name: str
    kind: str
    params: dict[str, Any] = Field(description="Stored parameters, defaults filled in")
    owner_id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class PortfolioCreate(_Body):
    """A portfolio bound to exactly one market environment: a replay environment
    (``replay_environment_id``) or one path of a simulation run (``simulation_run_id``
    plus ``path_index``)."""

    name: Name
    strategy_id: uuid.UUID
    initial_capital: Capital
    cost_model: LinearCostModel = Field(default_factory=LinearCostModel)
    slippage_model: SlippageConfig = Field(default_factory=FixedBpsSlippage)
    replay_environment_id: uuid.UUID | None = None
    simulation_run_id: uuid.UUID | None = None
    path_index: int | None = Field(default=None, ge=0, le=2_147_483_647)

    def binding_errors(self) -> list[dict[str, Any]]:
        """What is wrong with the environment binding, in the problem ``errors`` shape
        (empty when it is valid). Mirrors the ``portfolio_environment_binding`` CHECK."""

        def error(field: str, message: str) -> dict[str, Any]:
            return {"location": ["body", field], "message": message, "type": "binding"}

        neither = "bind the portfolio to a replay_environment_id or a simulation_run_id"
        both = "give replay_environment_id or simulation_run_id, not both"
        replay, simulation = self.replay_environment_id, self.simulation_run_id
        if replay is None and simulation is None:
            return [error("replay_environment_id", neither), error("simulation_run_id", neither)]
        if replay is not None and simulation is not None:
            return [error("replay_environment_id", both), error("simulation_run_id", both)]
        if simulation is not None and self.path_index is None:
            return [error("path_index", "a simulation binding needs a path_index")]
        if replay is not None and self.path_index is not None:
            return [error("path_index", "path_index applies only to a simulation binding")]
        return []

    @property
    def env_type(self) -> EnvType:
        return "replay" if self.replay_environment_id is not None else "simulation"


class PortfolioOut(BaseModel):
    id: uuid.UUID
    name: str
    strategy_id: uuid.UUID
    strategy_name: str
    strategy_kind: str
    owner_id: uuid.UUID
    initial_capital: str = Field(description="USD, 2 decimal places")
    base_currency: str
    cost_model: dict[str, Any]
    slippage_model: dict[str, Any]
    env_type: EnvType
    replay_environment_id: uuid.UUID | None
    simulation_run_id: uuid.UUID | None
    path_index: int | None
    source_fingerprint: str | None = Field(
        description="Frozen by the first run; null until the portfolio has run"
    )
    created_at: datetime
    updated_at: datetime


class RunAccepted(BaseModel):
    job_id: uuid.UUID
    portfolio_id: uuid.UUID
    status: JobStatus
    created: bool = Field(description="False when the idempotency key already had a job")


class RunOut(BaseModel):
    job_id: uuid.UUID
    portfolio_id: uuid.UUID
    status: JobStatus
    progress: float = Field(ge=0, le=1, description="Sessions committed / sessions in total")
    attempts: int
    max_attempts: int
    error: str | None
    result: dict[str, Any] | None = Field(
        description="Final seq, hash and value once the run has succeeded"
    )
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class EventOut(BaseModel):
    seq: int
    type: str
    version: int
    event_time: datetime
    payload: dict[str, Any] = Field(description="Amounts and prices as decimal strings")
    prev_hash: str | None
    hash: str


class EventPage(BaseModel):
    items: list[EventOut] = Field(description="Ascending by seq, without gaps")
    next_cursor: int | None = Field(
        description="Pass as after_seq to get the next page; null on the last page"
    )


def money_text(value: Decimal) -> str:
    """A stored decimal exactly as stored (``format`` never switches to an exponent)."""
    return format(value, "f")


def validation_problem(errors: list[dict[str, Any]]) -> ServiceError:
    """A 422 in the shape of the kit's request validation errors: every entry names the
    offending field in ``location``."""
    return ServiceError(
        422,
        "Invalid request",
        "; ".join(f"{'.'.join(map(str, e['location'][1:]))}: {e['message']}" for e in errors),
        type_="urn:quantsim:problem:validation",
        extra={"errors": errors},
    )


def not_found(what: str) -> ServiceError:
    return ServiceError(
        404,
        f"{what} not found",
        f"No {what.lower()} has this id.",
        type_="urn:quantsim:problem:not-found",
    )
