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


def _imports(path: Path) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module.split(".")[0])
    return found


def test_metrics_need_numpy_only() -> None:
    # Trading depends on qs-quant without the calibration extra: K6 must never import
    # SciPy or statsmodels, directly or through the shared input checks
    package = ROOT / "src" / "qs_quant"
    for path in [*sorted((package / "metrics").rglob("*.py")), package / "_validation.py"]:
        assert _imports(path) & {"scipy", "statsmodels"} == set(), path.name
        local = {
            node.module
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
            if isinstance(node, ast.ImportFrom)
            and node.module
            and node.module.startswith("qs_quant")
        }
        assert not any(m.startswith("qs_quant.calibration") for m in local), path.name
