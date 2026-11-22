"""The history-only view a strategy reads (task A12, A-FR-02).

:class:`BarHistory` indexes every bar of a run once, by symbol and session. The engine then
asks it for a :class:`InMemoryHistoryView` at each session ``t``: a small immutable object
holding the shared index, ``t`` and the portfolio after the fills of ``t``. Building a view
copies nothing, so advancing one session costs O(1).

A view answers only for sessions ``<= t``. :meth:`InMemoryHistoryView.bar` raises
:class:`~qs_trading.domain.strategy.LookAheadError` for any later session, and
:meth:`~InMemoryHistoryView.bars` and :meth:`~InMemoryHistoryView.latest` never return a bar
after ``t``, so a strategy cannot see the future even when the index already holds it.
"""

from bisect import bisect_right
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

from qs_trading.domain.accounting import PortfolioState
from qs_trading.domain.strategy import Bar, LookAheadError

__all__ = ["BarHistory", "InMemoryHistoryView", "UnknownSymbol"]


class UnknownSymbol(KeyError):
    """A symbol that is not one of the environment's instruments."""


@dataclass(frozen=True, slots=True)
class _Series:
    """The bars of one symbol, oldest first, with their sessions for binary search."""

    bars: tuple[Bar, ...]
    sessions: tuple[int, ...]


class BarHistory:
    """Every bar of a run, indexed once. ``symbols`` fixes the instruments and their order;
    when omitted it is the sorted set of symbols in ``bars``. A symbol may miss sessions
    (ADR 08); two bars for one symbol and session are refused."""

    __slots__ = ("_series", "_symbols")

    def __init__(self, bars: Iterable[Bar], symbols: Sequence[str] | None = None) -> None:
        grouped: dict[str, dict[int, Bar]] = {}
        for item in bars:
            by_session = grouped.setdefault(item.symbol, {})
            if item.session in by_session:
                raise ValueError(f"two bars for {item.symbol} at session {item.session}")
            if item.session < 0:
                raise ValueError(f"a session index cannot be negative, got {item.session}")
            by_session[item.session] = item
        order = tuple(symbols) if symbols is not None else tuple(sorted(grouped))
        if len(set(order)) != len(order):
            raise ValueError("symbols must be unique")
        extra = sorted(set(grouped) - set(order))
        if extra:
            raise ValueError(f"bars for symbols outside the environment: {', '.join(extra)}")
        series: dict[str, _Series] = {}
        for symbol in order:
            ordered = tuple(grouped.get(symbol, {})[s] for s in sorted(grouped.get(symbol, {})))
            series[symbol] = _Series(ordered, tuple(b.session for b in ordered))
        self._symbols = order
        self._series: Mapping[str, _Series] = MappingProxyType(series)

    @property
    def symbols(self) -> tuple[str, ...]:
        return self._symbols

    def view(self, session: int, portfolio: PortfolioState) -> "InMemoryHistoryView":
        """What a strategy may see at ``session``, given the portfolio after its fills."""
        return InMemoryHistoryView(self, session, portfolio)

    def _series_of(self, symbol: str) -> _Series:
        try:
            return self._series[symbol]
        except KeyError:
            raise UnknownSymbol(symbol) from None


@dataclass(frozen=True, slots=True)
class InMemoryHistoryView:
    """A :class:`~qs_trading.domain.strategy.HistoryView` over a :class:`BarHistory`."""

    history: BarHistory
    current_session: int
    current_portfolio: PortfolioState

    def __post_init__(self) -> None:
        if self.current_session < 0:
            raise ValueError(f"a session index cannot be negative, got {self.current_session}")

    @property
    def session(self) -> int:
        return self.current_session

    @property
    def symbols(self) -> Sequence[str]:
        return self.history.symbols

    @property
    def portfolio(self) -> PortfolioState:
        return self.current_portfolio

    def bars(self, symbol: str, lookback: int | None = None) -> Sequence[Bar]:
        series = self.history._series_of(symbol)
        end = bisect_right(series.sessions, self.current_session)
        if lookback is None:
            return series.bars[:end]
        if lookback < 0:
            raise ValueError(f"lookback cannot be negative, got {lookback}")
        return series.bars[max(0, end - lookback) : end]

    def bar(self, symbol: str, session: int) -> Bar | None:
        series = self.history._series_of(symbol)
        if session > self.current_session:
            now = self.current_session
            raise LookAheadError(f"session {session} of {symbol} is after the current {now}")
        index = bisect_right(series.sessions, session) - 1
        if index >= 0 and series.sessions[index] == session:
            return series.bars[index]
        return None

    def latest(self, symbol: str) -> Bar | None:
        series = self.history._series_of(symbol)
        end = bisect_right(series.sessions, self.current_session)
        return series.bars[end - 1] if end else None
