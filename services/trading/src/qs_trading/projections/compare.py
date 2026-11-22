"""Row-for-row comparison of two projections of one log (task A15, A-FR-11).

The rebuild compares the projections stored by the live engine with the ones folded from
the log again. Rows are matched on their table's key; a row is ``missing`` when the log
implies it and the table lacks it, ``unexpected`` when the table holds it and the log does
not imply it, and ``changed`` when both have it with different column values (numbers
compare by value, so ``1.5`` and ``1.50`` are equal, as they are to the database).
"""

from collections.abc import Hashable, Mapping
from dataclasses import dataclass
from typing import Any

from qs_trading.projections.fold import Projection, Row

__all__ = ["TableDifference", "compare_projections"]


@dataclass(frozen=True, slots=True)
class TableDifference:
    """How one table differs from the log. Each entry names a row by its key; a changed
    row also names its differing columns."""

    table: str
    missing: tuple[str, ...] = ()
    unexpected: tuple[str, ...] = ()
    changed: tuple[str, ...] = ()

    def to_json(self) -> dict[str, Any]:
        return {
            "table": self.table,
            "missing": list(self.missing),
            "unexpected": list(self.unexpected),
            "changed": list(self.changed),
        }


def _label(table: str, key: Hashable) -> str:
    if table == "holding_history" and isinstance(key, tuple):
        seq, symbol = key
        return f"seq={seq} symbol={symbol}"
    if table == "order":
        return f"order_id={key}"
    if table == "portfolio_state_current":
        return "state"
    return f"seq={key}"


def _differing_columns(expected: Row, actual: Row) -> list[str]:
    return sorted(
        column
        for column in expected.keys() | actual.keys()
        if expected.get(column) != actual.get(column)
    )


def _compare_table(
    table: str, live: Mapping[Any, Row], rebuilt: Mapping[Any, Row]
) -> TableDifference | None:
    missing = [_label(table, key) for key in rebuilt if key not in live]
    unexpected = [_label(table, key) for key in live if key not in rebuilt]
    changed = []
    for key, expected in rebuilt.items():
        actual = live.get(key)
        if actual is None:
            continue
        columns = _differing_columns(expected, actual)
        if columns:
            changed.append(f"{_label(table, key)} ({', '.join(columns)})")
    if not (missing or unexpected or changed):
        return None
    return TableDifference(table, tuple(missing), tuple(unexpected), tuple(changed))


def compare_projections(live: Projection, rebuilt: Projection) -> tuple[TableDifference, ...]:
    """Every table where ``live`` (stored) differs from ``rebuilt`` (folded from the log);
    empty when they are identical row for row."""
    state_live = {} if live.state is None else {"state": live.state}
    state_rebuilt = {} if rebuilt.state is None else {"state": rebuilt.state}
    tables = (
        ("order", live.orders, rebuilt.orders),
        ("fill", live.fills, rebuilt.fills),
        ("holding_history", live.holdings, rebuilt.holdings),
        ("portfolio_value", live.values, rebuilt.values),
        ("portfolio_state_current", state_live, state_rebuilt),
    )
    found = (_compare_table(name, a, b) for name, a, b in tables)
    return tuple(difference for difference in found if difference is not None)
