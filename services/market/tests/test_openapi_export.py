"""K4: the frontend's generated types come from the committed OpenAPI document, so the document
must match the API. If this fails, the API changed: run scripts/export-openapi.py, then
`npm run gen:api` in frontend, and commit both (a page that used a removed field then fails the
frontend type check, which is the point)."""

import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "export-openapi.py"


def test_the_committed_openapi_document_matches_the_api() -> None:
    result = subprocess.run(  # noqa: S603 - our own script, no user input
        [sys.executable, str(SCRIPT), "--check", "market"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
