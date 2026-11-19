"""C1: the tick contract. Valid samples pass and every invalid sample fails, each for the reason
its name says (B-US-01). The fixtures that follow the contract are checked in test_fixtures.py."""

import pytest
from jsonschema import Draft202012Validator

from .contract_support import CONTRACTS, TICK_SCHEMA, load, tick_problems

SAMPLES = CONTRACTS / "events" / "samples"

# invalid sample -> a word that must appear in the first reason it is refused for
WHY = {
    "bad_decimal_exponent.json": "open: '1e2'",
    "price_as_json_number.json": "open: 100.5 is not of type 'string'",
    "negative_price.json": "low: '-99'",
    "high_below_low.json": "high: must not be below low",
    "zero_price.json": "open: a price must be above zero",
    "seq_zero.json": "seq: 0 is less than the minimum of 1",
    "wrong_env_type.json": "env_type: 'historical_replay' is not one of",
    "missing_symbol.json": "'symbol' is a required property",
    "synthetic_without_path_index.json": "'path_index' is a required property",
    "replay_with_path_index.json": "path_index: 3 is not of type 'null'",
    "bad_uuid.json": "env_id: 'not-a-uuid'",
    "timestamp_without_zone.json": "ts: '2020-01-02 21:00:00'",
    "negative_session.json": "session: -1 is less than the minimum of 0",
}


def test_the_schema_is_a_valid_json_schema() -> None:
    Draft202012Validator.check_schema(TICK_SCHEMA)


@pytest.mark.parametrize("path", sorted((SAMPLES / "valid").glob("*.json")), ids=lambda p: p.stem)
def test_every_valid_sample_passes(path) -> None:  # type: ignore[no-untyped-def]
    assert tick_problems(load(path)) == []


@pytest.mark.parametrize("name", sorted(WHY))
def test_every_invalid_sample_fails_for_its_reason(name: str) -> None:
    problems = tick_problems(load(SAMPLES / "invalid" / name))
    assert problems, f"{name} should be refused"
    assert any(WHY[name] in problem for problem in problems), problems


def test_every_invalid_sample_is_accounted_for() -> None:
    on_disk = {p.name for p in (SAMPLES / "invalid").glob("*.json")}
    assert on_disk == set(WHY), "add a reason in WHY for each invalid sample, and no stale entries"


def test_a_replay_and_a_synthetic_tick_share_one_shape() -> None:
    replay = load(SAMPLES / "valid" / "replay.json")
    synthetic = load(SAMPLES / "valid" / "synthetic.json")
    assert set(replay) <= set(synthetic) | {"session_date"}
    assert {r for r in TICK_SCHEMA["required"]} <= set(replay) & set(synthetic)


def test_consumers_ignore_fields_they_do_not_know() -> None:
    sample = load(SAMPLES / "valid" / "replay_class_share_with_extra_field.json")
    assert "a_field_added_in_a_later_version" in sample
    assert tick_problems(sample) == []
