"""C3: the committed fixtures follow the contracts, on every machine and in CI (no corpus needed).
That they are exactly what the recorded corpus makes is checked by
tests/realdata/test_contract_fixtures.py wherever the corpus exists (B-FR-01, B-US-01, B-US-09)."""

from collections import Counter
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from fakeredis import FakeAsyncRedis
from jsonschema import Draft202012Validator

from qs_market.main import build_app
from qs_template import Database
from qs_template.revocation import RevocationList
from tests.instrument_support import make_settings

from .contract_support import FIXTURES, load, tick_problems

REPLAY = load(FIXTURES / "replay_ticks_2020.json")
SYNTHETIC = load(FIXTURES / "synthetic_ticks.json")
CORRELATION = load(FIXTURES / "correlation_rolling_60_5.json")
REPLAY_SYMBOLS = ["AAPL", "KO", "MSFT", "NVDA", "TSLA"]


def test_every_fixture_says_how_it_was_made() -> None:
    for document in (REPLAY, SYNTHETIC, CORRELATION):
        assert "never edit by hand" in document["meta"]["made_by"]
        assert document["meta"]["regenerate"].endswith("make-fixtures.py")
        assert document["meta"]["source"]


def test_the_replay_ticks_follow_the_contract_in_feed_order() -> None:
    ticks: list[dict[str, Any]] = REPLAY["items"]
    assert len(ticks) == REPLAY["environment"]["tick_count"] == 1265
    assert [t["seq"] for t in ticks] == list(range(1, len(ticks) + 1))
    assert [(t["session"], t["symbol"]) for t in ticks] == sorted(
        (t["session"], t["symbol"]) for t in ticks
    )
    problems = {t["seq"]: tick_problems(t) for t in ticks if tick_problems(t)}
    assert problems == {}, list(problems.items())[:3]
    assert REPLAY["next_after_seq"] is None


def test_the_replay_ticks_describe_five_names_and_every_2020_session() -> None:
    ticks = REPLAY["items"]
    assert sorted({t["symbol"] for t in ticks}) == REPLAY_SYMBOLS
    assert set(Counter(t["symbol"] for t in ticks).values()) == {253}
    assert sorted({t["session"] for t in ticks}) == list(range(253))
    dates = sorted({date.fromisoformat(t["session_date"]) for t in ticks})
    assert dates[0] == date(2020, 1, 2) and dates[-1] == date(2020, 12, 31)
    assert all(t["env_type"] == "replay" and t["path_index"] is None for t in ticks)


def test_the_replay_ticks_share_one_environment_and_one_fingerprint() -> None:
    environment = REPLAY["environment"]
    assert {t["env_id"] for t in REPLAY["items"]} == {environment["id"]}
    assert {t["source_fingerprint"] for t in REPLAY["items"]} == {environment["source_fingerprint"]}
    assert environment["source_fingerprint"].startswith("xxh3:")
    by_symbol = {i["symbol"]: i["id"] for i in environment["instruments"]}
    assert all(by_symbol[t["symbol"]] == t["instrument_id"] for t in REPLAY["items"])
    assert len(set(by_symbol.values())) == 5 and environment["frequency"] == "daily"


def test_the_replay_prices_are_adjusted_ones_that_differ_from_a_raw_split() -> None:
    # TSLA split 5 for 1 in Aug 2020 and AAPL 4 for 1: adjusted closes stay continuous across it
    closes = {
        t["session_date"]: Decimal(t["close"]) for t in REPLAY["items"] if t["symbol"] == "AAPL"
    }
    before, after = closes["2020-08-28"], closes["2020-08-31"]
    assert abs(after / before - 1) < Decimal("0.2"), (
        "an unadjusted split would show a 75 percent drop"
    )


def test_the_synthetic_fixture_is_three_gap_free_paths_of_flat_bars() -> None:
    run = SYNTHETIC["run"]
    paths = SYNTHETIC["paths"]
    assert [p["path_index"] for p in paths] == [0, 1, 2] == list(range(run["n_paths"]))
    for path in paths:
        ticks = path["items"]
        assert [t["seq"] for t in ticks] == list(range(1, 3 * run["n_steps"] + 1))
        assert {t["path_index"] for t in ticks} == {path["path_index"]}
        assert [t["session"] for t in ticks] == sorted(t["session"] for t in ticks)
        assert max(t["session"] for t in ticks) == run["n_steps"] - 1
        assert all(tick_problems(t) == [] for t in ticks)
        assert all(
            t["open"] == t["high"] == t["low"] == t["close"] and Decimal(t["volume"]) == 0
            for t in ticks
        )
        assert all(t["env_type"] == "synthetic" and t["scenario"] is None for t in ticks)
    assert {t["env_id"] for p in paths for t in p["items"]} == {run["id"]}
    assert 0 <= run["median_path_index"] < run["n_paths"]


def test_the_synthetic_steps_are_real_trading_sessions_in_order() -> None:
    first = SYNTHETIC["paths"][0]["items"]
    days = sorted({t["ts"][:10] for t in first})
    assert days[0] == "2021-01-04", "2021-01-01 is a market holiday"
    assert not any(date.fromisoformat(d).weekday() >= 5 for d in days)
    assert len(days) == SYNTHETIC["run"]["n_steps"]
    assert {t["ts"][11:] for t in first if t["ts"][:10] == "2021-01-04"} == {
        "21:00:00Z"
    }  # winter close
    assert {t["ts"][11:] for t in first if t["ts"][:10] == "2021-03-15"} == {
        "20:00:00Z"
    }  # summer close


def test_the_synthetic_paths_differ_from_each_other_and_stay_positive() -> None:
    finals = [
        tuple(t["close"] for t in path["items"] if t["session"] == SYNTHETIC["run"]["n_steps"] - 1)
        for path in SYNTHETIC["paths"]
    ]
    assert len(set(finals)) == 3
    assert all(Decimal(c) > 0 for final in finals for c in final)


def test_the_correlation_fixture_is_a_valid_answer_of_the_real_endpoint() -> None:
    settings = make_settings("postgresql+asyncpg://unused:unused@127.0.0.1:1/unused")
    app = build_app(
        settings, database=Database(settings), revocations=RevocationList(FakeAsyncRedis())
    )
    spec = app.openapi()
    schema = {"$ref": "#/components/schemas/CorrelationResponse", "components": spec["components"]}
    answer = {k: v for k, v in CORRELATION.items() if k != "meta"}
    Draft202012Validator(schema).validate(answer)
    assert CORRELATION["meta"]["request"]["rolling"] == {
        "length": 60, "step": 5, "start": "2019-01-02", "end": "2021-12-31",
    }  # fmt: skip


def test_the_correlation_matrices_are_square_symmetric_with_a_unit_diagonal() -> None:
    windows = CORRELATION["windows"]
    assert len(windows) > 100
    for window in windows:
        n = len(window["symbols"])
        assert (
            n == 6 and len(window["matrix"]) == n and all(len(row) == n for row in window["matrix"])
        )
        for i in range(n):
            assert window["matrix"][i][i] == "1.00000000"
            for j in range(n):
                assert window["matrix"][i][j] == window["matrix"][j][i]
        assert window["n_obs"] == 60
    starts = [w["start"] for w in windows]
    assert starts == sorted(starts)


@pytest.mark.parametrize(
    "name", ["replay_ticks_2020.json", "synthetic_ticks.json", "correlation_rolling_60_5.json"]
)
def test_fixtures_end_in_a_newline(name: str) -> None:
    # either line ending: git on Windows may check the files out with CRLF; the regeneration check
    # in realdata/test_contract_fixtures.py compares them with line endings normalised
    assert (FIXTURES / name).read_bytes().endswith(b"\n")
