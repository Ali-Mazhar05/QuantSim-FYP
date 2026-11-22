"""Validation against ``contracts/events/market.tick.v1.schema.json``: the JSON Schema plus the
rules it cannot express (prices above zero, high not below low). The same logic as the market
service's tests and as Lane A's consumer tests, so "valid" means one thing everywhere."""

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

CONTRACTS = Path(__file__).resolve().parents[3] / "contracts"
TICK_SCHEMA = json.loads((CONTRACTS / "events" / "market.tick.v1.schema.json").read_text("utf-8"))
_validator = Draft202012Validator(TICK_SCHEMA)


def tick_problems(tick: Any) -> list[str]:
    found = [
        f"{'/'.join(str(p) for p in error.absolute_path) or '(tick)'}: {error.message}"
        for error in sorted(_validator.iter_errors(tick), key=lambda e: list(e.absolute_path))
    ]
    if found or not isinstance(tick, dict):
        return found
    prices = {name: Decimal(tick[name]) for name in ("open", "high", "low", "close")}
    found += [f"{n}: a price must be above zero" for n, v in prices.items() if v <= 0]
    if prices["high"] < prices["low"]:
        found.append("high: must not be below low")
    return found
