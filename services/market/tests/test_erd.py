"""The committed ERD must always match the schema: regenerate it and compare."""

import importlib.util
from pathlib import Path
from types import ModuleType

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "erd.py"


def load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("market_erd", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_committed_erd_matches_the_table_definitions() -> None:
    erd = load_script()
    for path, content in erd.expected_files().items():
        assert path.exists(), f"{path} is missing; run uv run python scripts/erd.py"
        committed = path.read_text(encoding="utf-8").replace("\r\n", "\n")
        assert committed == content, f"{path.name} is stale; run uv run python scripts/erd.py"


def test_every_market_table_is_in_the_diagram() -> None:
    erd = load_script()
    diagram = erd.diagram()
    from qs_market.models import metadata

    for name in metadata.tables:
        assert f"    {name} {{" in diagram
