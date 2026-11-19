"""The market environment port (frozen for tasks A14 and A17).

A portfolio is bound to one market environment: a historical replay (``market``) or one
path of a simulation run (``simulation``). Both serve the same tick shape,
``market.tick.v1`` (contract C1, ADR 01), and the engine pulls them page by page with
``after_seq``. Two adapters implement this port: a file adapter over recorded fixtures
(A14) and an HTTP adapter over the C2 feeds (A17), so the engine is tested with no other
service running.

Tick rules (ADR 01 and 08): ``seq`` starts at 1 with no gaps; ticks are ordered by
``(session, symbol)``; ``session`` is the zero-based index of the session in the
environment; a symbol with no bar on a session has no tick for it; prices are split- and
dividend-adjusted; ``ts`` is the session close in UTC.

Until Lane B's C1 schema merges, :class:`Tick` follows the two ADRs; fields the schema adds
are ignored by the adapters.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal, Protocol

EnvType = Literal["replay", "simulation"]

DEFAULT_PAGE_SIZE = 1000
MAX_PAGE_SIZE = 5000


class MarketEnvironmentError(RuntimeError):
    """The environment cannot serve ticks."""


class FingerprintChanged(MarketEnvironmentError):
    """The data served no longer matches the fingerprint frozen at activation."""

    def __init__(self, expected: str, actual: str) -> None:
        super().__init__(f"source fingerprint changed from {expected} to {actual}")
        self.expected = expected
        self.actual = actual


class MissingAdjustedPrices(MarketEnvironmentError):
    """The window holds bars without adjusted prices (feed 422 ``missing_adjusted_prices``)."""


@dataclass(frozen=True, slots=True)
class Tick:
    seq: int
    session: int
    symbol: str
    ts: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal


@dataclass(frozen=True, slots=True)
class TickPage:
    """One page of ticks. ``next_after_seq`` is ``None`` on the last page; ``fingerprint``
    is the source fingerprint the page was served under (``X-Source-Fingerprint``)."""

    items: Sequence[Tick]
    next_after_seq: int | None
    fingerprint: str


@dataclass(frozen=True, slots=True)
class EnvironmentRef:
    """Which environment a portfolio is bound to; ``path_index`` only for simulations."""

    env_type: EnvType
    env_id: str
    path_index: int | None = None

    def __post_init__(self) -> None:
        if (self.env_type == "simulation") != (self.path_index is not None):
            raise ValueError("a simulation needs a path index and a replay takes none")


class MarketEnvironment(Protocol):
    """Reads one environment's ticks."""

    @property
    def ref(self) -> EnvironmentRef: ...

    async def activate(self) -> str:
        """Prepares the environment for reading and returns the source fingerprint frozen
        now; a run records it in ``RUN_STARTED``."""
        ...

    async def fingerprint(self) -> str:
        """The current source fingerprint of the data served."""
        ...

    async def ticks(self, after_seq: int = 0, limit: int = DEFAULT_PAGE_SIZE) -> TickPage:
        """Ticks with ``seq > after_seq``, at most ``limit`` (up to :data:`MAX_PAGE_SIZE`)."""
        ...
