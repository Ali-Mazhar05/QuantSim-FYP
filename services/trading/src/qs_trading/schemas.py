"""Request and response bodies of the Trading API (task A16).

Money is an exact decimal string in JSON, never a float (NFR-INT-001): request amounts
may be a decimal string or a whole number, and responses always carry strings with the
stored number of places. Strategy parameters, cost models and slippage models are stored
as JSON objects in the canonical form their domain models dump (decimals as strings,
defaults filled in), and are returned exactly as stored.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from qs_template import ServiceError
from qs_trading.domain.costs import ExactDecimal, LinearCostModel
from qs_trading.domain.slippage import FixedBpsSlippage, SlippageConfig
from qs_trading.domain.strategies import KINDS

__all__ = [
    "ChainReportOut",
    "CostModelOut",
    "DemoEnvironmentOut",
    "EventOut",
    "EventPage",
    "FillOut",
    "FillPage",
    "HoldingChangeOut",
    "HoldingHistoryPage",
    "HoldingsOut",
    "JobDurationsOut",
    "JobQueueOut",
    "JobStatus",
    "MetricsOut",
    "OpsMetricsOut",
    "OutboxBacklogOut",
    "PortfolioCreate",
    "PortfolioOut",
    "PositionOut",
    "RebuildOut",
    "RunAccepted",
    "RunOut",
    "SlippageModelOut",
    "StateOut",
    "StrategyIn",
    "StrategyOut",
    "TableDifferenceOut",
    "ValuePointOut",
    "forbidden",
    "log_broken",
    "money_text",
    "not_found",
    "run_in_progress",
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


class DemoEnvironmentOut(BaseModel):
    """A demo market environment the worker can run over (LOCAL and DEV only); bind a
    portfolio to it with ``replay_environment_id``."""

    id: uuid.UUID
    name: str
    env_type: EnvType
    sessions: int = Field(ge=0, description="Trading sessions in the environment")
    start_date: date | None
    end_date: date | None


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


class CostModelOut(BaseModel):
    """A portfolio's stored cost model: every parameter as a decimal string."""

    fixed: str
    per_share: str
    pct: str


class SlippageModelOut(BaseModel):
    """A portfolio's stored slippage model: its kind and basis points as a decimal string."""

    kind: Literal["fixed_bps", "volume"]
    bps: str


class PortfolioOut(BaseModel):
    id: uuid.UUID
    name: str
    strategy_id: uuid.UUID
    strategy_name: str
    strategy_kind: str
    owner_id: uuid.UUID
    initial_capital: str = Field(description="USD, 2 decimal places")
    base_currency: str
    cost_model: CostModelOut
    slippage_model: SlippageModelOut
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


Money = Annotated[str, Field(description="Decimal string, USD")]
Price = Annotated[str, Field(description="Decimal string, USD per share")]


class FillOut(BaseModel):
    """One ``fill`` row: an order filled at ``session`` with its slippage and costs."""

    seq: int = Field(description="The ORDER_FILLED event")
    order_id: str
    session: int
    symbol: str
    side: Literal["buy", "sell"]
    quantity: int
    reference_price: Price
    fill_price: Price
    slippage: Price
    cost_fixed: Money
    cost_per_share: Money
    cost_percentage: Money
    cost_total: Money = Field(description="cost_fixed + cost_per_share + cost_percentage")
    cash_after: Money


class FillPage(BaseModel):
    items: list[FillOut] = Field(description="Ascending by seq")
    next_cursor: int | None = Field(
        description="Pass as after_seq to get the next page; null on the last page"
    )


class PositionOut(BaseModel):
    symbol: str
    quantity: int
    cost_basis: Money


class HoldingsOut(BaseModel):
    """The current positions and cash (the ``portfolio_state_current`` row)."""

    portfolio_id: uuid.UUID
    last_seq: int = Field(description="The last event folded in; 0 before the first run")
    last_session: int | None
    cash: Money | None = Field(description="Null until the portfolio has run")
    positions: list[PositionOut] = Field(description="Open positions, by symbol")


class HoldingChangeOut(BaseModel):
    """One ``holding_history`` row: a symbol's position right after the fill at ``seq``
    (quantity and cost basis zero when the fill closed it)."""

    seq: int
    session: int
    symbol: str
    quantity: int
    cost_basis: Money


class HoldingHistoryPage(BaseModel):
    items: list[HoldingChangeOut] = Field(description="Ascending by seq")
    next_cursor: int | None = Field(
        description="Pass as after_seq to get the next page; null on the last page"
    )


class ValuePointOut(BaseModel):
    """One ``portfolio_value`` row: the portfolio marked at the close of ``session``."""

    session: int
    ts: datetime
    seq: int = Field(description="The VALUED event")
    cash: Money
    market_value: Money
    value: Money
    realised_pnl: Money
    unrealised_pnl: Money
    total_costs: Money


class StateOut(BaseModel):
    """The portfolio right after the event at ``seq``, folded from the verified log."""

    portfolio_id: uuid.UUID
    seq: int
    hash: str
    session: int | None
    initial_capital: Money
    cash: Money
    positions: list[PositionOut]
    realised_pnl: Money
    total_costs: Money
    open_orders: list[str]
    last_value: Money | None = Field(description="The latest valuation at or before seq")
    last_valued_seq: int | None


class TableDifferenceOut(BaseModel):
    """How one stored table differs from the log; every entry names a row by its key."""

    table: str
    missing: list[str]
    unexpected: list[str]
    changed: list[str]


class RebuildOut(BaseModel):
    portfolio_id: uuid.UUID
    status: Literal["identical", "differs"]
    events: int
    final_seq: int = Field(description="0 for an empty log")
    final_hash: str | None
    differences: list[TableDifferenceOut]
    applied: bool = Field(description="The rebuilt rows replaced the differing stored ones")


class ChainReportOut(BaseModel):
    portfolio_id: uuid.UUID
    valid: bool
    events: int
    last_seq: int = Field(description="The end of the intact prefix")
    last_hash: str | None
    broken_seq: int | None
    reason: str | None


Ratio = Annotated[str | None, Field(description="Decimal string; null while pending")]


class MetricsOut(BaseModel):
    """Run metrics. Trades, costs, sessions and the final value are computed from the
    projections; the ratios come from the shared metrics library and are null, and named
    in ``pending``, until it is available."""

    portfolio_id: uuid.UUID
    final_seq: int = Field(description="The last event folded in; 0 before the first run")
    final_hash: str | None
    sessions: int = Field(description="Valued sessions")
    initial_capital: Money
    final_value: Money | None = Field(description="Value at the last session; null before")
    trades: int = Field(description="Number of fills")
    total_costs: Money = Field(description="Sum of cost_total over the fills")
    total_return: Ratio
    volatility: Ratio
    sharpe: Ratio
    max_drawdown: Ratio
    turnover: Ratio
    pending: list[str] = Field(description="The metrics not computed yet")


class JobQueueOut(BaseModel):
    """Depth of the job queue for one job kind, by status (A-NFR-14)."""

    kind: str
    queued: int
    running: int
    succeeded: int
    failed: int
    oldest_queued_seconds: float | None = Field(
        description="Age of the oldest queued job in seconds; null when none is queued"
    )


class JobDurationsOut(BaseModel):
    """Run time of the last finished jobs, from first claim (``started_at``) to
    ``finished_at``, so retries are included (A-NFR-14)."""

    window: int = Field(description="How many of the most recently finished jobs are asked for")
    count: int = Field(description="How many finished jobs the figures cover (<= window)")
    p50_seconds: float | None
    p95_seconds: float | None
    max_seconds: float | None


class OutboxBacklogOut(BaseModel):
    """Events written to the outbox and not yet published (A-NFR-14, NFR-OBS-003)."""

    pending: int
    oldest_pending_seconds: float | None = Field(
        description="Age of the oldest unpublished event in seconds; null when none waits"
    )


class OpsMetricsOut(BaseModel):
    """Operational figures of the service for admins and the DEV live check."""

    generated_at: datetime
    queue: JobQueueOut
    durations: JobDurationsOut
    outbox: OutboxBacklogOut


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


FORBIDDEN = "urn:quantsim:problem:forbidden"


def forbidden(detail: str) -> ServiceError:
    """A 403 in the kit's shape, for a caller whose role passes but who may not act on
    this resource."""
    return ServiceError(403, "Forbidden", detail, type_=FORBIDDEN)


RUN_IN_PROGRESS = "urn:quantsim:problem:run-in-progress"


def run_in_progress(job_id: uuid.UUID) -> ServiceError:
    """A 409 for a new run while the portfolio's run ``job_id`` is queued or running."""
    return ServiceError(
        409,
        "Run in progress",
        f"Run {job_id} of this portfolio is still queued or running; wait for it to finish.",
        type_=RUN_IN_PROGRESS,
        extra={"job_id": str(job_id)},
    )


LOG_BROKEN = "urn:quantsim:problem:log-broken"


def log_broken(seq: int | None, reason: str | None) -> ServiceError:
    """A 409 for a log that fails verification or does not fold: nothing can be derived
    from it until it is repaired. ``broken_seq`` names the first bad event."""
    return ServiceError(
        409,
        "Trade log is broken",
        f"The trade log breaks at seq {seq}: {reason}",
        type_=LOG_BROKEN,
        extra={"broken_seq": seq, "reason": reason},
    )
