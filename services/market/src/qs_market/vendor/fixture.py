"""A vendor that is a directory of recorded responses.

Used by tests, demos and any environment that must not spend the real key. It opens no
connection. ``{SYMBOL}.json`` holds the response body a real Tiingo call returned; it is
mapped by the same code as a live response and filtered to the requested window the way
the vendor does it.
"""

import re
from datetime import date
from pathlib import Path
from typing import Any

from qs_market.vendor.base import UnknownSymbol
from qs_market.vendor.tiingo import parse_prices

_SAFE_SYMBOL = re.compile(r"^[A-Za-z0-9._-]{1,20}$")


class FixtureSource:
    name = "fixture"

    def __init__(self, directory: Path) -> None:
        self._directory = directory

    def __repr__(self) -> str:
        return f"FixtureSource({str(self._directory)!r})"

    async def fetch_daily(self, symbol: str, start: date, end: date) -> list[dict[str, Any]]:
        if not _SAFE_SYMBOL.match(symbol):
            raise UnknownSymbol(f"no recorded response for {symbol!r}")
        path = self._directory / f"{symbol.upper()}.json"
        if not path.is_file():
            raise UnknownSymbol(f"no recorded response for {symbol!r}")
        low, high = start.isoformat(), end.isoformat()
        return [
            row for row in parse_prices(path.read_bytes()) if low <= (row["date"] or "") <= high
        ]
