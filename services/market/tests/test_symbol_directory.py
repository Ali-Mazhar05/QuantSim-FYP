"""The Nasdaq symbol directory parser, the source and the recorded real fixture."""

import logging
import os
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from qs_market.data.universe import UNIVERSE
from qs_market.symbol_directory import (
    NASDAQ_FILE,
    NASDAQ_HEADER,
    OTHER_FILE,
    OTHER_HEADER,
    DirectoryError,
    DirectorySource,
    load_directory,
    normalise,
    parse_nasdaq_listed,
    parse_other_listed,
)

FIXTURE = Path(__file__).parent / "fixtures" / "symdir"

NASDAQ_TEXT = f"""{NASDAQ_HEADER}
AAPL|Apple Inc. - Common Stock|Q|N|N|40|N|N
QQQ|Invesco QQQ Trust, Series 1|G|N|N|40|Y|N
AACG|ATA Creativity Global - American Depositary Shares|S|N|D|100|N|N
ZXYZ.A|Nasdaq Symbology Test Common Stock|Q|Y|N|100|N|N
File Creation Time: 1014202612:11|||||||
"""

OTHER_TEXT = f"""{OTHER_HEADER}
BRK.B|Berkshire Hathaway Inc. New Common Stock|N|BRK.B|N|40|N|BRK.B
SPY|State Street SPDR S&P 500 ETF Trust|P|SPY|Y|40|N|SPY
BIT|Some Bats Fund|Z|BIT|Y|100|N|BIT
ODD|Unmapped venue|F|ODD|N|100|N|ODD
File Creation Time: 1014202612:11||||||
"""

# Where the directory disagrees with the seed universe's listing exchange. The universe
# keeps XNYS for every ETF and for WMT; the directory lists the ETFs on NYSE Arca and
# Walmart moved to Nasdaq. Pinned here so the difference is visible and a new one fails.
EXCHANGE_DIFFERENCES = {
    "WMT": "XNAS",
    "SPY": "ARCX",
    "IWM": "ARCX",
    "DIA": "ARCX",
    "VTI": "ARCX",
    "VOO": "ARCX",
    "XLF": "ARCX",
    "XLK": "ARCX",
    "XLE": "ARCX",
    "GLD": "ARCX",
}


def test_nasdaq_listed_rows() -> None:
    directory = parse_nasdaq_listed(NASDAQ_TEXT)
    assert len(directory) == 4
    aapl = directory.lookup("AAPL")
    assert aapl is not None
    assert (aapl.name, aapl.exchange, aapl.is_etf, aapl.is_test_issue, aapl.financial_status) == (
        "Apple Inc. - Common Stock",
        "XNAS",
        False,
        False,
        "N",
    )
    qqq = directory.lookup("QQQ")
    assert qqq is not None and qqq.is_etf
    aacg = directory.lookup("AACG")
    assert aacg is not None and aacg.financial_status == "D" and not aacg.is_normal
    test = directory.lookup("ZXYZ.A")
    assert test is not None and test.is_test_issue


def test_other_listed_rows_map_the_exchange() -> None:
    directory = parse_other_listed(OTHER_TEXT)
    exchanges = {}
    for symbol in ("BRK.B", "SPY", "BIT", "ODD"):
        entry = directory.lookup(symbol)
        assert entry is not None
        exchanges[symbol] = entry.exchange
    assert exchanges == {"BRK.B": "XNYS", "SPY": "ARCX", "BIT": "BATS", "ODD": None}
    spy = directory.lookup("SPY")
    assert spy is not None and spy.is_etf and spy.is_normal


def test_footer_gives_the_creation_time_in_utc() -> None:
    directory = parse_nasdaq_listed(NASDAQ_TEXT)
    assert directory.created_at == datetime(2026, 10, 14, 16, 11, tzinfo=UTC)  # 12:11 EDT


def test_missing_or_bad_footer_gives_unknown_time() -> None:
    no_footer = "\n".join(NASDAQ_TEXT.splitlines()[:-1])
    assert parse_nasdaq_listed(no_footer).created_at is None
    bad = NASDAQ_TEXT.replace("1014202612:11", "not a time")
    assert parse_nasdaq_listed(bad).created_at is None


def test_class_share_forms_are_one_symbol() -> None:
    directory = parse_other_listed(OTHER_TEXT)
    assert normalise("brk-b") == normalise("BRK.B") == "BRK.B"
    for form in ("BRK.B", "BRK-B", "brk.b", " brk-b "):
        entry = directory.lookup(form)
        assert entry is not None and entry.symbol == "BRK.B"


def test_malformed_rows_are_skipped_and_counted() -> None:
    text = f"""{NASDAQ_HEADER}
AAPL|Apple Inc.|Q|N|N|40|N|N
TOOFEW|name|Q
|no symbol|Q|N|N|40|N|N
BADFLAG|name|Q|X|N|40|N|N
AAPL|duplicate|Q|N|N|40|N|N

MSFT|Microsoft|Q|N|N|40|N|N
File Creation Time: 1014202612:11|||||||
"""
    directory = parse_nasdaq_listed(text)
    assert sorted(directory.entries) == ["AAPL", "MSFT"]
    assert directory.skipped == 4
    kept = directory.lookup("AAPL")
    assert kept is not None and kept.name == "Apple Inc."


@pytest.mark.parametrize("text", ["", "\n\n", "Wrong|Header\nAAPL|x|Q|N|N|1|N|N\n"])
def test_no_header_raises(text: str) -> None:
    with pytest.raises(DirectoryError):
        parse_nasdaq_listed(text)


def test_header_without_rows_raises() -> None:
    with pytest.raises(DirectoryError, match="no rows"):
        parse_other_listed(f"{OTHER_HEADER}\nFile Creation Time: 1014202612:11||||||\n")
    with pytest.raises(DirectoryError, match="no rows"):
        parse_other_listed(f"{OTHER_HEADER}\nbroken line\n")


def test_directory_is_read_only() -> None:
    directory = parse_nasdaq_listed(NASDAQ_TEXT)
    with pytest.raises(TypeError):
        directory.entries["X"] = directory.entries["AAPL"]  # type: ignore[index]
    with pytest.raises(AttributeError):
        directory.skipped = 5  # type: ignore[misc]


def test_every_universe_symbol_is_in_the_recorded_directory() -> None:
    directory = load_directory(FIXTURE)
    differences = {}
    for symbol, _name, _sector, exchange, asset_class in UNIVERSE:
        entry = directory.lookup(symbol)
        assert entry is not None, symbol
        assert entry.is_etf == (asset_class == "etf"), symbol
        assert entry.is_normal and not entry.is_test_issue, symbol
        if entry.exchange != exchange:
            differences[symbol] = entry.exchange
    assert differences == EXCHANGE_DIFFERENCES


def test_recorded_fixture_has_the_real_footer_and_edge_cases() -> None:
    directory = load_directory(FIXTURE)
    assert directory.skipped == 0
    assert directory.created_at == datetime(2026, 10, 14, 16, 11, tzinfo=UTC)
    brk = directory.lookup("BRK-B")
    assert brk is not None and brk.exchange == "XNYS"
    assert any(e.is_test_issue for e in directory.entries.values())
    assert any(not e.is_normal for e in directory.entries.values())


def _copy_fixture(target: Path) -> None:
    for name in (NASDAQ_FILE, OTHER_FILE):
        (target / name).write_bytes((FIXTURE / name).read_bytes())


def test_load_directory_with_a_missing_file_raises(tmp_path: Path) -> None:
    _copy_fixture(tmp_path)
    (tmp_path / OTHER_FILE).unlink()
    with pytest.raises(DirectoryError, match=OTHER_FILE):
        load_directory(tmp_path)


def test_fresh_directory_does_not_warn(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    _copy_fixture(tmp_path)
    source = DirectorySource(tmp_path, max_age_days=14)
    with caplog.at_level(logging.WARNING):
        directory = source.get(now=datetime(2026, 10, 20, tzinfo=UTC))
    assert len(directory) > 40
    assert caplog.records == []


def test_stale_directory_warns_and_is_still_returned(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    _copy_fixture(tmp_path)
    source = DirectorySource(tmp_path, max_age_days=14)
    with caplog.at_level(logging.WARNING):
        directory = source.get(now=datetime(2026, 12, 1, tzinfo=UTC))
    assert directory.lookup("AAPL") is not None
    assert any("days old" in r.getMessage() for r in caplog.records)


def test_source_rereads_a_changed_file(tmp_path: Path) -> None:
    _copy_fixture(tmp_path)
    source = DirectorySource(tmp_path, max_age_days=14)
    now = datetime(2026, 10, 15, tzinfo=UTC)
    assert source.get(now).lookup("NEWCO") is None
    path = tmp_path / NASDAQ_FILE
    lines = path.read_text(encoding="utf-8").splitlines()
    lines.insert(1, "NEWCO|New Co - Common Stock|Q|N|N|100|N|N")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    later = time.time() + 5
    os.utime(path, (later, later))
    assert source.get(now).lookup("NEWCO") is not None
