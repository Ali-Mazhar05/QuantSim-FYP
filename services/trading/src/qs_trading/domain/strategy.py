"""Strategy interface and the history-only view it reads (frozen for tasks A12 and A14).

At each session ``t`` the engine calls ``strategy.on_bar(view)``. The view exposes bars for
sessions ``<= t`` only (A-FR-02): asking for anything later raises :class:`LookAheadError`,
so look-ahead bias is a bug that fails loudly rather than a result that looks too good.

Strategies are pure: no I/O, no clock, no randomness, so a rerun on the same source
fingerprint gives the same orders and the same final hash (A-FR-12).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, ClassVar, Protocol

from qs_trading.domain.accounting import PortfolioState
from qs_trading.domain.orders import OrderIntent


class LookAheadError(LookupError):
    """A strategy asked for data after the current session."""


@dataclass(frozen=True, slots=True)
class Bar:
    """One daily bar of one instrument, split- and dividend-adjusted (ADR 08)."""

    session: int
    symbol: str
    ts: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal


class HistoryView(Protocol):
    """What a strategy may see at the current session."""

    @property
    def session(self) -> int:
        """The current session index ``t`` (zero-based, ADR 01)."""
        ...

    @property
    def symbols(self) -> Sequence[str]:
        """The environment's instruments, in a fixed order."""
        ...

    @property
    def portfolio(self) -> PortfolioState:
        """Cash and positions after every fill up to and including session ``t``."""
        ...

    def bars(self, symbol: str, lookback: int | None = None) -> Sequence[Bar]:
        """Bars of ``symbol`` for sessions ``<= t``, oldest first; the last ``lookback`` of
        them when given. A symbol with no bar on a session is absent from it (ADR 08)."""
        ...

    def bar(self, symbol: str, session: int) -> Bar | None:
        """The bar of ``symbol`` at ``session``; ``None`` when it had none. Raises
        :class:`LookAheadError` when ``session > t``."""
        ...

    def latest(self, symbol: str) -> Bar | None:
        """The most recent bar of ``symbol`` at or before ``t``."""
        ...


class Strategy(Protocol):
    """A built-in strategy kind (ADR 05: ``kind`` plus ``params`` JSONB)."""

    kind: ClassVar[str]

    def on_bar(self, view: HistoryView) -> Sequence[OrderIntent]:
        """Orders to place after seeing session ``t``. They are validated, then market
        orders fill at the open of ``t + 1``."""
        ...


class StrategyFactory(Protocol):
    """Builds a strategy from validated parameters; the registry maps ``kind`` to one."""

    def __call__(self, params: Mapping[str, Any]) -> Strategy: ...
