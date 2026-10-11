"""Regenerate the market_db entity-relationship diagram from the table definitions.

    uv run python scripts/erd.py            # rewrite docs/diagrams/market_db.{mmd,md}
    uv run python scripts/erd.py --check    # exit 1 if the committed files are stale

The diagram comes from the same tables the migrations are tested against, and
tests/test_erd.py fails whenever the committed files differ from a fresh generation, so
the ERD in the repository always matches the real schema.
"""

import argparse
import sys
from pathlib import Path

from qs_market.models import LOGICAL_REFERENCES, metadata
from qs_template.audit import audit_metadata
from qs_template.erd import mermaid_erd
from qs_template.messaging import messaging_metadata

REPO_ROOT = Path(__file__).resolve().parents[3]
DIAGRAMS = REPO_ROOT / "docs" / "diagrams"

INTRO = """\
# market_db: entity-relationship diagram

Database of the Market Data service (M1), PostgreSQL 17 with TimescaleDB.

**Generated, do not edit by hand.** Run `uv run python scripts/erd.py` in
`services/market` after any schema change; `tests/test_erd.py` fails while this file is
out of date. The source is the table definitions in
`services/market/src/qs_market/models.py` (checked against migration `0001` by
`tests/test_schema.py`) plus the shared outbox, processed-events and audit tables from
`libs/qs_template`.

Pictures for reports, `market_db.svg` and `market_db.png` next to this file, are rendered
from `market_db.mmd`; re-render them after regenerating:

    cd docs/diagrams
    npx -y @mermaid-js/mermaid-cli@11.4.2 -i market_db.mmd -o market_db.svg -b white
    npx -y @mermaid-js/mermaid-cli@11.4.2 -i market_db.mmd -o market_db.png -b white -s 2

How to read it:
- `PK` primary key, `FK` foreign key, `UK` unique. `"23,8"` is the numeric precision and
  scale: prices are exact decimals with 8 places, never floating point.
- `"optional"` columns may be empty; every other column is required.
- Solid lines are foreign keys. Dotted lines are references the schema deliberately does
  not enforce with a foreign key (hypertables and append-only history keep none).
- `bar` and `return_series` are TimescaleDB hypertables partitioned by `session_date`.
- `audit_log` and `processed_events` are not linked: the audit log records changes to
  `instrument` by table name and row id, and processed events hold ids of events from
  other services.
"""


def diagram() -> str:
    return mermaid_erd(
        metadata,
        messaging_metadata,
        audit_metadata,
        title="market_db",
        references=LOGICAL_REFERENCES,
    )


def markdown(mermaid: str) -> str:
    return f"{INTRO}\n```mermaid\n{mermaid}```\n"


def expected_files() -> dict[Path, str]:
    mermaid = diagram()
    return {DIAGRAMS / "market_db.mmd": mermaid, DIAGRAMS / "market_db.md": markdown(mermaid)}


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
