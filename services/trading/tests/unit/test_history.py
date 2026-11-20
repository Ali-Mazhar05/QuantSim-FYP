"""The history-only view (A12, A-FR-02): nothing after the current session is visible."""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import pytest

from qs_trading.domain.accounting import open_portfolio
from qs_trading.domain.history import BarHistory, InMemoryHistoryView, UnknownSymbol
from qs_trading.domain.orders import OrderIntent
from qs_trading.domain.strategy import Bar, HistoryView, LookAheadError

START = datetime(2026, 1, 5, 21, tzinfo=UTC)


def bar(symbol: str, session: int, close: str) -> Bar:
    px = D(close)
    return Bar(session, symbol, START + timedelta(days=session), px, px, px, px, D(1000))


# AAA trades every session 0..4; BBB has no bar at session 2 (ADR 08)
BARS = [bar("AAA", s, str(10 + s)) for s in range(5)] + [
    bar("BBB", s, str(20 + s)) for s in (0, 1, 3, 4)
]


def view_at(session: int) -> InMemoryHistoryView:
    return BarHistory(BARS, ["AAA", "BBB"]).view(session, open_portfolio("1000"))


def test_view_satisfies_the_protocol() -> None:
    view: HistoryView = view_at(2)
    assert view.session == 2
    assert list(view.symbols) == ["AAA", "BBB"]
    assert view.portfolio.cash == D("1000.00")


def test_bars_stop_at_the_current_session() -> None:
    view = view_at(2)
    assert [b.session for b in view.bars("AAA")] == [0, 1, 2]
    assert [b.session for b in view.bars("BBB")] == [0, 1]
    assert [b.close for b in view.bars("AAA", lookback=2)] == [D(11), D(12)]
    assert view.bars("AAA", lookback=10) == view.bars("AAA")
    assert view.bars("AAA", lookback=0) == ()


def test_reading_session_t_plus_one_raises() -> None:
    view = view_at(2)
    with pytest.raises(LookAheadError, match="session 3"):
        view.bar("AAA", 3)
    with pytest.raises(LookAheadError):
        view.bar("BBB", 99)


def test_bar_at_or_before_t() -> None:
    view = view_at(2)
    assert view.bar("AAA", 2) == bar("AAA", 2, "12")
    assert view.bar("AAA", 0) == bar("AAA", 0, "10")
    assert view.bar("BBB", 2) is None  # no bar that session, but not in the future
    assert view.bar("AAA", -1) is None


def test_latest_is_the_last_bar_at_or_before_t() -> None:
    assert view_at(2).latest("BBB") == bar("BBB", 1, "21")
    assert view_at(3).latest("BBB") == bar("BBB", 3, "23")
    assert BarHistory([bar("AAA", 3, "5")]).view(1, open_portfolio("1")).latest("AAA") is None


def test_a_session_past_the_data_sees_everything_and_nothing_more() -> None:
    view = view_at(10)
    assert len(view.bars("AAA")) == 5
    assert view.bar("AAA", 7) is None
    with pytest.raises(LookAheadError):
        view.bar("AAA", 11)


def test_advancing_shares_the_index() -> None:
    history = BarHistory(BARS)
    state = open_portfolio("1000")
    views = [history.view(t, state) for t in range(5)]
    assert [len(v.bars("AAA")) for v in views] == [1, 2, 3, 4, 5]
    assert all(v.history is history for v in views)


def test_symbols_default_to_sorted_and_may_have_no_bars() -> None:
    assert BarHistory(BARS).symbols == ("AAA", "BBB")
    history = BarHistory(BARS, ["BBB", "AAA", "CCC"])
    view = history.view(4, open_portfolio("1"))
    assert list(view.symbols) == ["BBB", "AAA", "CCC"]
    assert view.bars("CCC") == ()
    assert view.latest("CCC") is None


def test_unknown_symbol_raises() -> None:
    view = view_at(2)
    with pytest.raises(UnknownSymbol):
        view.bars("ZZZ")
    with pytest.raises(UnknownSymbol):
        view.bar("ZZZ", 0)
    with pytest.raises(UnknownSymbol):
        view.latest("ZZZ")


@pytest.mark.parametrize(
    ("bars", "symbols", "message"),
    [
        ([bar("AAA", 1, "1"), bar("AAA", 1, "2")], None, "two bars"),
        ([bar("AAA", 0, "1")], ["BBB"], "outside the environment"),
        ([bar("AAA", -1, "1")], None, "negative"),
        ([], ["AAA", "AAA"], "unique"),
    ],
)
def test_bad_history_is_refused(bars: list[Bar], symbols: list[str] | None, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        BarHistory(bars, symbols)


def test_bad_arguments() -> None:
    with pytest.raises(ValueError, match="lookback"):
        view_at(2).bars("AAA", lookback=-1)
    with pytest.raises(ValueError, match="negative"):
        BarHistory(BARS).view(-1, open_portfolio("1"))


class Peeker:
    """A strategy with look-ahead bias: it reads tomorrow's bar."""

    kind = "peeker"

    def on_bar(self, view: HistoryView) -> Sequence[OrderIntent]:
        view.bar("AAA", view.session + 1)
        return ()


def test_a_strategy_that_peeks_fails_loudly() -> None:
    with pytest.raises(LookAheadError):
        Peeker().on_bar(view_at(0))
