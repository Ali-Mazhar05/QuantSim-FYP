"""The Nasdaq Trader symbol directory: which symbols exist, where they list, and whether
they are test issues or in a deficient state.

Two public pipe-delimited files, each ending in a ``File Creation Time:`` footer:

- ``nasdaqlisted.txt``: Symbol|Security Name|Market Category|Test Issue|Financial Status|
  Round Lot Size|ETF|NextShares
- ``otherlisted.txt``: ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|
  Test Issue|NASDAQ Symbol

Parsing never raises on a malformed row: the row is skipped and counted. A file with no
header or no rows at all raises :class:`DirectoryError`, because that is a wrong file and
not a bad line.

Class shares: the directory writes ``BRK.B``, vendors write ``BRK-B``. Both sides are
compared after one rule, :func:`normalise`: upper case, and every ``-`` becomes ``.``.
"""

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import MappingProxyType
from zoneinfo import ZoneInfo

from qs_template import ServiceError

log = logging.getLogger(__name__)

NASDAQ_FILE = "nasdaqlisted.txt"
OTHER_FILE = "otherlisted.txt"

NASDAQ_HEADER = (
    "Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares"
)
OTHER_HEADER = (
    "ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol"
)

# Every Nasdaq-listed security trades on the Nasdaq market whatever its tier
NASDAQ_MIC = "XNAS"
# The "Exchange" column of otherlisted.txt. A code not listed here gives exchange None.
OTHER_EXCHANGES: Mapping[str, str] = MappingProxyType(
    {
        "A": "XASE",  # NYSE American
        "N": "XNYS",
        "P": "ARCX",  # NYSE Arca
        "Z": "BATS",  # Cboe BZX
        "V": "IEXG",
        "M": "XCHI",  # NYSE Chicago
    }
)

NORMAL_STATUS = "N"
_FOOTER = "File Creation Time:"
_NEW_YORK = ZoneInfo("America/New_York")


class DirectoryError(ValueError):
    """The file is not a symbol directory (no header, or no rows), or cannot be read."""


def normalise(symbol: str) -> str:
    """The one comparison form: upper case, and the dash class-share separator becomes a
    dot, so ``brk-b`` and ``BRK.B`` are the same symbol."""
    return symbol.strip().upper().replace("-", ".")


@dataclass(frozen=True, slots=True)
class DirectoryEntry:
    symbol: str  # as the directory writes it
    name: str
    exchange: str | None  # MIC, None when the directory's code is not one we map
    is_etf: bool
    is_test_issue: bool
    financial_status: str  # N is normal; D, E, Q, G, H, J, K are deficient, delinquent or bankrupt

    @property
    def is_normal(self) -> bool:
        return self.financial_status == NORMAL_STATUS


@dataclass(frozen=True, slots=True)
class SymbolDirectory:
    entries: Mapping[str, DirectoryEntry]  # keyed by normalised symbol, read only
    created_at: datetime | None  # the older footer time of the parts, UTC; None when unknown
    skipped: int  # malformed or duplicate rows

    def lookup(self, symbol: str) -> DirectoryEntry | None:
        return self.entries.get(normalise(symbol))

    def __len__(self) -> int:
        return len(self.entries)

    def merged(self, other: "SymbolDirectory") -> "SymbolDirectory":
        """Both listings in one. A symbol in both keeps this directory's entry."""
        entries = {**other.entries, **self.entries}
        duplicates = len(self.entries) + len(other.entries) - len(entries)
        created_at = None
        if self.created_at is not None and other.created_at is not None:
            created_at = min(self.created_at, other.created_at)
        return SymbolDirectory(
            entries=MappingProxyType(entries),
            created_at=created_at,
            skipped=self.skipped + other.skipped + duplicates,
        )

    def age(self, now: datetime) -> timedelta | None:
        return None if self.created_at is None else now - self.created_at


_RowParser = Callable[[list[str]], DirectoryEntry | None]


def parse_nasdaq_listed(text: str) -> SymbolDirectory:
    return _parse(text, NASDAQ_HEADER, _nasdaq_row)


def parse_other_listed(text: str) -> SymbolDirectory:
    return _parse(text, OTHER_HEADER, _other_row)


def load_directory(folder: Path) -> SymbolDirectory:
    """Read both files of a folder. A missing or unreadable file raises, so a wrong
    setting is found when the service starts and not at the first instrument add."""
    parts = []
    for file_name, parse in ((NASDAQ_FILE, parse_nasdaq_listed), (OTHER_FILE, parse_other_listed)):
        try:
            text = (folder / file_name).read_text(encoding="utf-8-sig", errors="replace")
        except OSError as exc:
            raise DirectoryError(f"cannot read {file_name}: {exc.strerror or exc}") from exc
        parts.append(parse(text))
    return parts[0].merged(parts[1])


def _parse(text: str, header: str, row_parser: _RowParser) -> SymbolDirectory:
    header_columns = header.split("|")
    entries: dict[str, DirectoryEntry] = {}
    skipped = 0
    created_at: datetime | None = None
    seen_header = False
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if not seen_header:
            if [c.strip() for c in line.split("|")][: len(header_columns)] != header_columns:
                raise DirectoryError("the first line is not the expected header")
            seen_header = True
            continue
        if line.startswith(_FOOTER):
            created_at = _footer_time(line)
            continue
        entry = row_parser(line.split("|"))
        if entry is None or normalise(entry.symbol) in entries:
            skipped += 1
            continue
        entries[normalise(entry.symbol)] = entry
    if not seen_header:
        raise DirectoryError("the file is empty")
    if not entries:
        raise DirectoryError("the file has a header but no rows")
    return SymbolDirectory(MappingProxyType(entries), created_at, skipped)


def _flag(value: str) -> bool | None:
    return {"Y": True, "N": False}.get(value.strip())


def _nasdaq_row(fields: list[str]) -> DirectoryEntry | None:
    if len(fields) < 7:
        return None
    symbol, name, _category, test, status, _lot, etf = (f.strip() for f in fields[:7])
    is_test, is_etf = _flag(test), _flag(etf)
    if not symbol or is_test is None or is_etf is None:
        return None
    return DirectoryEntry(symbol, name, NASDAQ_MIC, is_etf, is_test, status or NORMAL_STATUS)


def _other_row(fields: list[str]) -> DirectoryEntry | None:
    if len(fields) < 7:
        return None
    symbol, name, exchange, _cqs, etf, _lot, test = (f.strip() for f in fields[:7])
    is_test, is_etf = _flag(test), _flag(etf)
    if not symbol or not exchange or is_test is None or is_etf is None:
        return None
    return DirectoryEntry(
        symbol, name, OTHER_EXCHANGES.get(exchange), is_etf, is_test, NORMAL_STATUS
    )


def _footer_time(line: str) -> datetime | None:
    """``File Creation Time: 1014202612:11`` is MMDDYYYYHH:MM in New York time."""
    value = line.removeprefix(_FOOTER).split("|")[0].strip()
    try:
        return datetime.strptime(value, "%m%d%Y%H:%M").replace(tzinfo=_NEW_YORK).astimezone(UTC)
    except ValueError:
        return None


class DirectorySource:
    """The directory of a folder, re-read when either file changes, so a refreshed
    download is picked up without a restart. A directory older than ``max_age_days``
    logs a warning each time it is used and is still used."""

    def __init__(self, folder: Path, *, max_age_days: int) -> None:
        self._folder = folder
        self._max_age = timedelta(days=max_age_days)
        self._stamp: tuple[int, int] | None = None
        self._directory: SymbolDirectory | None = None

    def get(self, now: datetime | None = None) -> SymbolDirectory:
        try:
            stamp = (
                (self._folder / NASDAQ_FILE).stat().st_mtime_ns,
                (self._folder / OTHER_FILE).stat().st_mtime_ns,
            )
        except OSError as exc:
            raise DirectoryError(f"symbol directory files not found: {exc.strerror}") from exc
        if self._directory is None or stamp != self._stamp:
            self._directory = load_directory(self._folder)
            self._stamp = stamp
            if self._directory.skipped:
                log.warning("symbol directory: skipped %d malformed rows", self._directory.skipped)
        age = self._directory.age(now or datetime.now(UTC))
        if age is None:
            log.warning("symbol directory has no readable creation time, so its age is unknown")
        elif age > self._max_age:
            log.warning(
                "symbol directory is %d days old (limit %d days); refresh it with "
                "scripts/fetch_symbol_directory.py",
                age.days,
                self._max_age.days,
            )
        return self._directory


def validate_new_instrument(directory: SymbolDirectory, *, symbol: str, asset_class: str) -> None:
    """Raise a 422 when the directory does not allow this instrument to be added."""
    entry = directory.lookup(symbol)
    field = "symbol"
    message = None
    if entry is None:
        message = f"{symbol} is not in the Nasdaq symbol directory."
    elif entry.is_test_issue:
        message = f"{symbol} is a test issue, not a tradable security."
    elif not entry.is_normal:
        message = (
            f"{symbol} has financial status {entry.financial_status} (deficient, delinquent "
            "or bankrupt) in the Nasdaq symbol directory."
        )
    elif entry.is_etf != (asset_class == "etf"):
        field = "asset_class"
        actual = "an ETF" if entry.is_etf else "not an ETF"
        message = f"{symbol} is {actual} in the directory, but asset_class is {asset_class}."
    if message is None:
        return
    raise ServiceError(
        422,
        "Invalid request",
        message,
        type_="urn:quantsim:problem:validation",
        extra={
            "errors": [{"location": ["body", field], "message": message, "type": "symbol_directory"}]
        },
    )
