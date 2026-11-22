"""A-NFR-04: no binary float in the money code. Money, prices and quantities are
``Decimal`` in the domain, the engine core and the projections; the only place ``float``
may appear there is a check that refuses one (``isinstance(value, float)``).

Floats elsewhere in the service (timeouts, durations, progress, the ops figures) are not
money and are left alone."""

import ast
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[2] / "src" / "qs_trading"
MONEY_CODE = sorted(
    [
        *(SOURCE / "domain").rglob("*.py"),
        *(SOURCE / "projections").rglob("*.py"),
        SOURCE / "engine" / "core.py",
    ]
)


def _refusal_checks(tree: ast.AST) -> set[int]:
    """Ids of the ``float`` names inside the type argument of an ``isinstance`` call."""
    allowed: set[int] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "isinstance"
            and len(node.args) == 2
        ):
            allowed |= {id(n) for n in ast.walk(node.args[1]) if isinstance(n, ast.Name)}
    return allowed


def _floats(path: Path) -> list[int]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    allowed = _refusal_checks(tree)
    found = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and node.id == "float" and id(node) not in allowed
    ]
    found += [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, float)
    ]
    return sorted(found)


def test_the_money_code_is_found() -> None:
    assert len(MONEY_CODE) > 10
    assert all(path.exists() for path in MONEY_CODE)


@pytest.mark.parametrize("path", MONEY_CODE, ids=lambda p: p.relative_to(SOURCE).as_posix())
def test_no_float_in_the_money_code(path: Path) -> None:
    assert _floats(path) == [], f"float used in {path.name}; use Decimal (NFR-INT-001)"


def test_the_rule_catches_a_float(tmp_path: Path) -> None:
    sample = tmp_path / "sample.py"
    sample.write_text(
        "def price(x: float) -> object:\n"
        "    if isinstance(x, bool | float):\n"
        "        raise TypeError\n"
        "    return x * 1.5\n",
        encoding="utf-8",
    )
    assert _floats(sample) == [1, 4]
