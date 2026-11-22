"""Regenerate the simulation_db entity-relationship diagram from the table definitions.

    uv run python scripts/erd.py            # rewrite docs/diagrams/simulation_db.{mmd,md}
    uv run python scripts/erd.py --check    # exit 1 if the committed files are stale

The diagram comes from the same tables the migrations are tested against, and
tests/test_erd.py fails whenever the committed files differ from a fresh generation, so
the ERD in the repository always matches the real schema.
"""

import argparse
import sys
from pathlib import Path

from qs_simulation.models import LOGICAL_REFERENCES, metadata
from qs_template.audit import audit_metadata
from qs_template.erd import mermaid_erd
from qs_template.messaging import messaging_metadata

REPO_ROOT = Path(__file__).resolve().parents[3]
DIAGRAMS = REPO_ROOT / "docs" / "diagrams"

INTRO = """\
# simulation_db: entity-relationship diagram

Database of the Simulation service (M2), PostgreSQL 17.

**Generated, do not edit by hand.** Run `uv run python scripts/erd.py` in
`services/simulation` after any schema change; `tests/test_erd.py` fails while this file is
out of date. The source is the table definitions in
`services/simulation/src/qs_simulation/models.py` (checked against the migrations by
`tests/test_schema.py`) plus the job queue, outbox, processed-events and audit tables from
`libs/qs_template`.

How to read it:
- `PK` primary key, `FK` foreign key, `UK` unique. `"23,10"` is the numeric precision and
  scale: prices are exact decimals with 10 places, never floating point.
- `"optional"` columns may be empty; every other column is required.
- Solid lines are foreign keys. Dotted lines are references the schema deliberately does
  not enforce with a foreign key: `instrument_ref` is a cache of the market service's
  instruments for display, so nothing points at it by constraint.
- `run_instrument` points at `calibration (id, instrument_id)`, so a run cannot use another
  instrument's calibration, even through raw SQL.
- `path_value` holds every path of a small run; a larger run keeps its seed and
  `path_quantile` and regenerates a path on demand (ADR 03).
"""


def diagram() -> str:
    return mermaid_erd(
        metadata,
        messaging_metadata,
        audit_metadata,
        title="simulation_db",
        references=LOGICAL_REFERENCES,
    )


def markdown(mermaid: str) -> str:
    return f"{INTRO}\n```mermaid\n{mermaid}```\n"


def expected_files() -> dict[Path, str]:
    mermaid = diagram()
    return {
        DIAGRAMS / "simulation_db.mmd": mermaid,
        DIAGRAMS / "simulation_db.md": markdown(mermaid),
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
