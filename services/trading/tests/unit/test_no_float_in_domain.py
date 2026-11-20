"""A-NFR-04 (NFR-INT-001): no ``float`` in the domain, the engine or the projections.

Every module under ``qs_trading/domain``, ``engine`` and ``projections`` is parsed with
:mod:`ast` and fails this lint on a float literal (``0.5``, ``1e-3``), a ``float(...)``
call or ``float`` anywhere in a type: annotations (string ones included), aliases and
casts. The one use left is the refusal itself: ``isinstance(value, float)`` (or
``bool | float``) in the second argument of ``isinstance``/``issubclass``, which is how
the domain turns a float away.

An exception needs an entry in :data:`ALLOWED` with the module, the name it sits in and
the reason; an entry nothing matches any more fails too, so the list never goes stale.
"""

import ast
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[2] / "src" / "qs_trading"
CHECKED = ("domain", "engine", "projections")

ALLOWED: dict[tuple[str, str], str] = {
    (
        "engine/runner.py",
        "Progress",
    ): "the K1 job progress callback (qs_template.jobs.ProgressReporter) takes the share "
    "of sessions done as a float in [0, 1]; it is never money and never hashed or stored "
    "in the trade log",
}
"""(module relative to ``qs_trading``, enclosing name) -> why a float is needed there."""


@dataclass(frozen=True)
class Finding:
    module: str
    line: int
    scope: str  # the function, class or assigned name the float sits in; "" at top level
    what: str

    def __str__(self) -> str:
        where = f" in {self.scope}" if self.scope else ""
        return f"{self.module}:{self.line}{where}: {self.what}"


def _refusal_names(tree: ast.AST) -> set[int]:
    """ids of the ``float`` names that only test for a float, to refuse it."""
    allowed: set[int] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in ("isinstance", "issubclass")
            and len(node.args) == 2
        ):
            allowed.update(id(name) for name in ast.walk(node.args[1]))
    return allowed


def _annotation_strings(tree: ast.AST) -> Iterator[tuple[ast.Constant, str]]:
    """String annotations (``x: "float"``), which the plain walk sees only as text."""
    annotations: list[ast.expr | None] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            arguments = node.args
            every = [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs]
            every += [a for a in (arguments.vararg, arguments.kwarg) if a is not None]
            annotations += [a.annotation for a in every]
            annotations.append(node.returns)
        elif isinstance(node, ast.AnnAssign):
            annotations.append(node.annotation)
    for annotation in annotations:
        if annotation is None:
            continue
        for part in ast.walk(annotation):
            if isinstance(part, ast.Constant) and isinstance(part.value, str):
                yield part, part.value


def _scopes(tree: ast.AST) -> dict[int, str]:
    """The innermost function, class or assignment target around every node."""
    scope_of: dict[int, str] = {}

    def visit(node: ast.AST, scope: str) -> None:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            scope = node.name
        elif isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name):
                scope = target.id
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            scope = node.target.id
        elif isinstance(node, ast.TypeAlias):
            scope = node.name.id
        scope_of[id(node)] = scope
        for child in ast.iter_child_nodes(node):
            visit(child, scope)

    visit(tree, "")
    return scope_of


def float_findings(source: str, module: str) -> list[Finding]:
    """Every float use in ``source`` that the rule forbids."""
    tree = ast.parse(source, filename=module)
    refusals = _refusal_names(tree)
    scope_of = _scopes(tree)
    found: list[Finding] = []

    def add(node: ast.expr, what: str) -> None:
        found.append(Finding(module, node.lineno, scope_of.get(id(node), ""), what))

    calls = {
        id(node.func)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, float):
            add(node, f"float literal {node.value!r}")
        elif isinstance(node, ast.Name) and node.id == "float" and id(node) not in refusals:
            add(node, "float(...) call" if id(node) in calls else "float in a type")
    for text, value in _annotation_strings(tree):
        try:
            parsed = ast.parse(value, mode="eval")
        except SyntaxError:
            continue
        if any(isinstance(n, ast.Name) and n.id == "float" for n in ast.walk(parsed)):
            add(text, f"float in the string annotation {value!r}")
    return sorted(found, key=lambda f: (f.line, f.what))


def _modules() -> Iterator[tuple[str, str]]:
    for package in CHECKED:
        for path in sorted((PACKAGE / package).rglob("*.py")):
            yield path.relative_to(PACKAGE).as_posix(), path.read_text(encoding="utf-8")


def test_the_checked_packages_have_modules() -> None:
    modules = [name for name, _ in _modules()]
    for package in CHECKED:
        assert any(name.startswith(f"{package}/") for name in modules), package


def test_no_float_in_the_domain_engine_or_projections() -> None:
    findings = [f for name, source in _modules() for f in float_findings(source, name)]
    forbidden = [f for f in findings if (f.module, f.scope) not in ALLOWED]
    assert not forbidden, "float is not allowed here (NFR-INT-001); use Decimal:\n" + "\n".join(
        map(str, forbidden)
    )
    used = {(f.module, f.scope) for f in findings}
    stale = sorted(set(ALLOWED) - used)
    assert not stale, f"allow-list entries that no float needs any more: {stale}"


def test_the_rule_catches_every_kind_of_float() -> None:
    source = """
RATE = 0.5
TINY = 1e-3

def cost(x: float, y: "list[float]") -> float:
    return float(x)

Weights = dict[str, float]
weight: float | None = None

def refuse(value: object) -> None:
    if isinstance(value, bool | float):
        raise TypeError("no floats")
    if issubclass(type(value), float):
        raise TypeError("no floats")
"""
    found = [(f.line, f.scope, f.what) for f in float_findings(source, "sample.py")]
    assert found == [
        (2, "RATE", "float literal 0.5"),
        (3, "TINY", "float literal 0.001"),
        (5, "cost", "float in a type"),
        (5, "cost", "float in a type"),
        (5, "cost", "float in the string annotation 'list[float]'"),
        (6, "cost", "float(...) call"),
        (8, "Weights", "float in a type"),
        (9, "weight", "float in a type"),
    ]


def test_decimal_code_passes() -> None:
    source = """
from decimal import Decimal

RATE = Decimal("0.5")

def cost(x: Decimal) -> Decimal:
    return x * RATE / 3
"""
    assert float_findings(source, "sample.py") == []
