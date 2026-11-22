"""Version traceability (C-NFR-09) and purity (C-NFR-07)."""

import ast
import tomllib
from pathlib import Path

import qs_quant

ROOT = Path(__file__).resolve().parents[1]

# The only modules the library may import: NumPy now, SciPy and statsmodels for K5, and
# side-effect-free standard library modules. Anything doing I/O fails this test.
ALLOWED = {
    "numpy",
    "scipy",
    "statsmodels",
    "math",
    "dataclasses",
    "typing",
    "collections",
    "decimal",
    "__future__",
    "qs_quant",
}


def test_version_matches_pyproject() -> None:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert qs_quant.__version__ == data["project"]["version"]


def test_library_imports_nothing_that_does_io() -> None:
    offenders: list[str] = []
    for path in sorted((ROOT / "src" / "qs_quant").rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            offenders += [f"{path.name}: {n}" for n in names if n.split(".")[0] not in ALLOWED]
    assert offenders == []
