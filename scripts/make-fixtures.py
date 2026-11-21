"""Make (or check) the recorded fixtures in contracts/fixtures/ (C3).

    uv run --frozen --all-packages python scripts/make-fixtures.py            # write the files
    uv run --frozen --all-packages python scripts/make-fixtures.py --check    # fail if one is stale

The work is a market test, tests/realdata/test_contract_fixtures.py: it loads the recorded Tiingo
corpus through the real ingestion pipeline into a real database and writes what the real code
returns, so a fixture can never disagree with the service. It needs two things, never the network:

    QS_REALDATA_DIR     the folder of recorded {SYMBOL}.json files (never committed)
    TEST_DATABASE_URL   a PostgreSQL + TimescaleDB server, e.g. postgresql+asyncpg://qs:qs@localhost:55433/qs

Regenerating from the 40-name universe, once Lane C has loaded it, is the same command with that
corpus. The fixtures are never edited by hand.
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MARKET = REPO / "services" / "market"
TEST = "tests/realdata/test_contract_fixtures.py"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail if a committed fixture is stale")
    args = parser.parse_args(argv)
    needed = ("QS_REALDATA_DIR", "TEST_DATABASE_URL")
    missing = [name for name in needed if not os.environ.get(name)]
    if missing:
        print(f"set {' and '.join(missing)} (see the top of this file)", file=sys.stderr)
        return 2
    env = {**os.environ, "QS_WRITE_FIXTURES": "0" if args.check else "1"}
    command = [sys.executable, "-m", "pytest", TEST, "-q", "-p", "no:cacheprovider"]
    return subprocess.run(command, cwd=MARKET, env=env, check=False).returncode  # noqa: S603


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
