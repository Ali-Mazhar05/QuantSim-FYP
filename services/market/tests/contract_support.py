"""Validation of the contracts in ``contracts/``: the JSON Schema plus the rules JSON Schema cannot
express. Lane A's consumer tests and the fixture tests use the same function, so "valid" means one
thing everywhere."""

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

CONTRACTS = Path(__file__).resolve().parents[3] / "contracts"
FIXTURES = CONTRACTS / "fixtures"
TICK_SCHEMA = json.loads((CONTRACTS / "events" / "market.tick.v1.schema.json").read_text("utf-8"))
_validator = Draft202012Validator(TICK_SCHEMA)


def tick_problems(tick: Any) -> list[str]:
    """Every reason a tick breaks ``market.tick.v1``, as "where: what"; empty when valid."""
    found = [
        f"{'/'.join(str(p) for p in error.absolute_path) or '(tick)'}: {error.message}"
        for error in sorted(_validator.iter_errors(tick), key=lambda e: list(e.absolute_path))
    ]
    if found or not isinstance(tick, dict):
        return found
    prices = {name: Decimal(tick[name]) for name in ("open", "high", "low", "close")}
    for name, value in prices.items():
        if value <= 0:
            found.append(f"{name}: a price must be above zero")
    if prices["high"] < prices["low"]:
        found.append("high: must not be below low")
    return found


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))
