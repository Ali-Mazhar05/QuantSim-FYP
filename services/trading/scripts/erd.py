"""Regenerate the trading_db entity-relationship diagram from the table definitions.

    uv run python scripts/erd.py            # rewrite docs/diagrams/trading_db.{mmd,md}
    uv run python scripts/erd.py --check    # exit 1 if the committed files are stale

The diagram comes from the same tables the migrations are tested against, and
tests/test_erd.py fails whenever the committed files differ from a fresh generation, so
the ERD in the repository always matches the real schema.
"""

import argparse
import sys
from pathlib import Path

from qs_template.erd import mermaid_erd
from qs_template.messaging import messaging_metadata
from qs_trading.models import metadata

REPO_ROOT = Path(__file__).resolve().parents[3]
DIAGRAMS = REPO_ROOT / "docs" / "diagrams"

INTRO = """\
# trading_db: entity-relationship diagram

Database of the Trading service (Lane A), PostgreSQL 17 with TimescaleDB.

**Generated, do not edit by hand.** Run `uv run python scripts/erd.py` in
`services/trading` after any schema change; `tests/test_erd.py` fails while this file is
out of date. The source is the table definitions in
`services/trading/src/qs_trading/models.py` (checked against the migrations by the trading
schema tests) plus the job queue, outbox and processed-events tables from `libs/qs_template`.

How to read it:
- `PK` primary key, `FK` foreign key, `UK` unique. `"23,10"` is the numeric precision and
  scale: money and quantities are exact decimals, never floating point.
- `"optional"` columns may be empty; every other column is required.
- `trade_event` is the hash-chained event log of a run; holdings, values, metrics and the
  current state are projections rebuilt from it.
- `instrument_ref` is a cache of the market service's instruments, used for display.
"""


def diagram() -> str:
    return mermaid_erd(metadata, messaging_metadata, title="trading_db")


def markdown(mermaid: str) -> str:
    return f"{INTRO}\n```mermaid\n{mermaid}```\n"


def expected_files() -> dict[Path, str]:
    mermaid = diagram()
    return {
        DIAGRAMS / "trading_db.mmd": mermaid,
        DIAGRAMS / "trading_db.md": markdown(mermaid),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--check", action="store_true", help="fail if the files are stale")
    args = parser.parse_args()
    stale = []
    for path, content in expected_files().items():
        current = path.read_text(encoding="utf-8") if path.exists() else None
        if current == content:
            continue
        if args.check:
            stale.append(path)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8", newline="\n")
            print(f"wrote {path.relative_to(REPO_ROOT)}")
    if stale:
        names = ", ".join(str(p.relative_to(REPO_ROOT)) for p in stale)
        sys.exit(f"stale: {names}; run uv run python scripts/erd.py")


if __name__ == "__main__":
    main()
