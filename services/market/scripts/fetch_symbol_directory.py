"""Download the Nasdaq symbol directory for instrument validation.

    python scripts/fetch_symbol_directory.py --out /var/lib/quantsim/symdir
    QS_SYMBOL_DIRECTORY_DIR=/var/lib/quantsim/symdir   # then point the service at the folder

Fetches nasdaqlisted.txt and otherlisted.txt over https from nasdaqtrader.com. Each file
is written to a temporary name and renamed, and only after it parses as a directory, so a
failed or partial download never replaces a good file. The files are public. Run it by
hand or from a scheduled job on the host; the test suite and CI never run it.
"""

import argparse
import os
import sys
import tempfile
import urllib.request
from pathlib import Path

from qs_market.symbol_directory import (
    NASDAQ_FILE,
    OTHER_FILE,
    DirectoryError,
    parse_nasdaq_listed,
    parse_other_listed,
)

BASE_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/"
TIMEOUT_SECONDS = 60
FILES = {NASDAQ_FILE: parse_nasdaq_listed, OTHER_FILE: parse_other_listed}


def fetch(name: str, out: Path) -> int:
    url = BASE_URL + name
    if not url.startswith("https://"):
        raise ValueError("only https is allowed")
    with urllib.request.urlopen(url, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310
        text = response.read().decode("utf-8", errors="replace")
    directory = FILES[name](text)  # raises when it is not a symbol directory
    out.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=out, prefix=name, suffix=".part")
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as file:
            file.write(text)
        os.replace(temporary, out / name)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
    return len(directory)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, required=True, help="folder to write the two files to")
    args = parser.parse_args()
    failures = 0
    for name in FILES:
        try:
            print(f"{name:18} {fetch(name, args.out)} symbols")
        except (OSError, DirectoryError, ValueError) as exc:
            failures += 1
            print(f"{name:18} FAILED  {type(exc).__name__}: {exc}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
