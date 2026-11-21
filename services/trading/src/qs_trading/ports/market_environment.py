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

:class:`Tick` keeps the fields of ``market.tick.v1`` the engine uses; the others
(``env_id``, ``env_type``, ``instrument_id``, ``session_date``, ``path_index``,
``scenario`` ...) are ignored by the adapters.

**Paging** (ADR 01, decision DL-008): ``limit`` defaults to :data:`DEFAULT_PAGE_SIZE` (500)
and is at most :data:`MAX_PAGE_SIZE` (2000), the convention of the market service's
lists; a page is ``{items, next_after_seq}``. No caller may ask for more than 2000.

**Fingerprint** (ADR 08, decision DL-004): ``xxh3:`` over the served values, computed by the
provider. A consumer cannot recompute it (the bar revision is not served); it only compares
the value it reads with the one frozen at activation.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal, Protocol

EnvType = Literal["replay", "simulation"]

DEFAULT_PAGE_SIZE = 500
"""The page size when none is asked for (ADR 01, DL-008)."""
MAX_PAGE_SIZE = 2000
"""The largest page a feed serves (ADR 01, DL-008); a larger ``limit`` is refused."""


class MarketEnvironmentError(RuntimeError):
    """The environment cannot serve ticks."""


class FingerprintChanged(MarketEnvironmentError):
    """The data served no longer matches the fingerprint frozen at activation."""

    def __init__(self, expected: str, actual: str) -> None:
        super().__init__(f"source fingerprint changed from {expected} to {actual}")
        self.expected = expected
        self.actual = actual


class MissingAdjustedPrices(MarketEnvironmentError):
    """The window holds bars without adjusted prices (feed 422
    ``urn:quantsim:problem:missing-adjusted-prices``). ``missing`` is the number of such
    bars per symbol, as the problem's ``missing`` member gives it (empty when it gave
    none)."""

    def __init__(self, message: str, missing: Mapping[str, int] | None = None) -> None:
        super().__init__(message)
        self.missing: dict[str, int] = dict(missing or {})


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
