"""The correlation module against numpy and pandas on the same input, then its rules:
missing sessions, constant series, minimum observations, rolling arithmetic and the
fingerprint."""

import math
import random
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from qs_market import correlation as c
from qs_market.correlation import Observation, Window

START = date(2024, 1, 1)


def days(n: int) -> list[date]:
    return [START + timedelta(days=i) for i in range(n)]


def make(
    n: int = 80, symbols: int = 4, seed: int = 7, source: str = "h"
) -> dict[str, dict[date, Observation]]:
    rng = random.Random(seed)  # noqa: S311
    base = [rng.gauss(0, 0.01) for _ in range(n)]
    out: dict[str, dict[date, Observation]] = {}
    for s in range(symbols):
        mix = 0.3 * s
        out[f"id{s}"] = {
            d: Observation(base[i] * mix + rng.gauss(0, 0.01), f"{source}{s}{i}")
            for i, d in enumerate(days(n))
        }
    return out


def labels(series: dict[str, dict[date, Observation]]) -> dict[str, str]:
    return {k: k.upper() for k in series}


def frame(series: dict[str, dict[date, Observation]]) -> pd.DataFrame:
    return pd.DataFrame({k: {d: o.value for d, o in v.items()} for k, v in series.items()})


def as_array(matrix: c.Matrix) -> np.ndarray:
    return np.array([[math.nan if v is None else float(v) for v in row] for row in matrix.values])


def test_matches_numpy_and_pandas_on_the_same_input() -> None:
    series = make()
    window = Window(days(80)[0], days(80)[-1])
    [matrix] = c.correlate(series, [window], labels=labels(series))
    keys = sorted(series)
    data = np.array([[series[k][d].value for d in days(80)] for k in keys])
    assert matrix.n_obs == 80
    assert matrix.instruments == [k.upper() for k in keys]
    assert np.allclose(as_array(matrix), np.corrcoef(data), atol=1e-8, rtol=0)
    assert np.allclose(as_array(matrix), frame(series)[keys].corr().to_numpy(), atol=1e-8)


def test_unrounded_agreement_with_numpy_is_within_1e_12() -> None:
    series = make(n=300, symbols=5, seed=3)
    keys = sorted(series)
    data = np.array([[series[k][d].value for d in days(300)] for k in keys])
    expected = np.corrcoef(data)
    centred = [c._centred([series[k][d].value for d in days(300)]) for k in keys]
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            a, b = centred[i], centred[j]
            assert a is not None and b is not None
            assert abs(c._pearson(a, b) - expected[i, j]) < 1e-12


def test_missing_sessions_are_dropped_for_every_instrument() -> None:
    series = make(n=60, symbols=3)
    gone = days(60)[10:14]
    for d in gone:
        del series["id1"][d]
    series["id2"][days(60)[30]] = Observation(math.nan, "x")
    window = Window(days(60)[0], days(60)[-1])
    [matrix] = c.correlate(series, [window], labels=labels(series))
    assert matrix.n_obs == 55
    keep = [d for d in days(60) if d not in gone and d != days(60)[30]]
    data = np.array([[series[k][d].value for d in keep] for k in sorted(series)])
    assert np.allclose(as_array(matrix), np.corrcoef(data), atol=1e-8)
    expected = frame(series).dropna().corr().to_numpy()
    assert np.allclose(as_array(matrix), expected, atol=1e-8)


def test_matrix_is_symmetric_with_exact_unit_diagonal_and_eight_places() -> None:
    series = make()
    [matrix] = c.correlate(series, [Window(days(80)[0], days(80)[-1])])
    size = len(series)
    for i in range(size):
        assert matrix.values[i][i] == "1.00000000"
        for j in range(size):
            assert matrix.values[i][j] == matrix.values[j][i]
            value = matrix.values[i][j]
            assert value is not None
            assert len(value.split(".")[1]) == 8
            assert "e" not in value.lower() and "nan" not in value.lower()
            assert -1 <= float(value) <= 1


def test_perfect_correlation_never_leaves_the_unit_interval() -> None:
    base = {d: Observation(math.sin(i), "s") for i, d in enumerate(days(30))}
    scaled = {d: Observation(3 * o.value + 1e-9, "t") for d, o in base.items()}
    opposite = {d: Observation(-o.value, "u") for d, o in base.items()}
    series = {"a": base, "b": scaled, "c": opposite}
    [matrix] = c.correlate(series, [Window(days(30)[0], days(30)[-1])])
    assert matrix.values[0][1] == "1.00000000"
    assert matrix.values[0][2] == "-1.00000000"


def test_constant_series_gives_null_with_a_reason_never_nan() -> None:
    series = make(n=40, symbols=3)
    series["id1"] = {d: Observation(0.001, "k") for d in days(40)}
    [matrix] = c.correlate(series, [Window(days(40)[0], days(40)[-1])], labels=labels(series))
    assert matrix.values[1] == [None, None, None]
    assert [row[1] for row in matrix.values] == [None, None, None]
    assert matrix.values[0][2] is not None
    reasons = {(a, b): r for a, b, r in matrix.unavailable}
    assert reasons[("ID0", "ID1")] == c.CONSTANT
    assert reasons[("ID1", "ID1")] == c.CONSTANT
    assert ("ID0", "ID2") not in reasons


def test_below_the_minimum_every_cell_is_null_with_a_reason() -> None:
    series = make(n=19, symbols=3)
    window = Window(days(19)[0], days(19)[-1])
    [short] = c.correlate(series, [window])
    assert short.n_obs == 19
    assert all(v is None for row in short.values for v in row)
    assert {r for *_, r in short.unavailable} == {c.INSUFFICIENT}
    assert len(short.unavailable) == 6
    [enough] = c.correlate(series, [window], min_observations=19)
    assert all(v is not None for row in enough.values for v in row)


def test_window_with_no_shared_session_is_all_null_not_an_error() -> None:
    series = make(n=30, symbols=2)
    [matrix] = c.correlate(series, [Window(date(2030, 1, 1), date(2030, 2, 1))])
    assert matrix.n_obs == 0
    assert all(v is None for row in matrix.values for v in row)


def test_windows_are_inclusive_at_both_ends() -> None:
    series = make(n=60, symbols=2)
    [matrix] = c.correlate(series, [Window(days(60)[5], days(60)[24])], min_observations=2)
    assert matrix.n_obs == 20


def test_rolling_windows_arithmetic() -> None:
    sessions = days(100)
    windows = c.rolling_windows(sessions, 60, 20)
    assert len(windows) == (100 - 60) // 20 + 1 == 3
    assert windows[0] == Window(sessions[0], sessions[59])
    assert windows[1] == Window(sessions[20], sessions[79])
    assert windows[2] == Window(sessions[40], sessions[99])
    assert c.rolling_windows(sessions, 100, 1) == [Window(sessions[0], sessions[99])]
    assert c.rolling_windows(sessions, 101, 1) == []
    assert len(c.rolling_windows(sessions, 2, 1)) == 99
    assert c.rolling_windows(list(reversed(sessions)), 60, 20) == windows


def test_rolling_windows_reject_bad_arguments_and_too_many() -> None:
    with pytest.raises(ValueError):
        c.rolling_windows(days(10), 1, 1)
    with pytest.raises(ValueError):
        c.rolling_windows(days(10), 5, 0)
    with pytest.raises(c.LimitExceeded):
        c.rolling_windows(days(400), 2, 1)
    assert len(c.rolling_windows(days(251), 2, 1)) == 250


def test_caps_on_instruments_windows_and_work() -> None:
    wide: dict[str, dict[date, Observation]] = {f"i{n:02d}": {} for n in range(41)}
    with pytest.raises(c.LimitExceeded):
        c.correlate(wide, [Window(START, START)])
    series = make(n=30, symbols=2)
    with pytest.raises(c.LimitExceeded):
        c.correlate(series, [Window(START, START)] * 251)
    forty = {f"i{n:02d}": {d: Observation(0.0, "") for d in days(300)} for n in range(40)}
    with pytest.raises(c.LimitExceeded):
        c.correlate(forty, [Window(days(300)[0], days(300)[-1])] * 250)


def test_forty_instruments_one_window_is_allowed() -> None:
    rng = random.Random(1)  # noqa: S311
    forty = {
        f"i{n:02d}": {d: Observation(rng.gauss(0, 1), str(n)) for d in days(120)} for n in range(40)
    }
    [matrix] = c.correlate(forty, [Window(days(120)[0], days(120)[-1])])
    assert len(matrix.values) == 40 and matrix.n_obs == 120


def fingerprint_of(series: dict[str, dict[date, Observation]], min_observations: int = 20) -> str:
    window = Window(days(40)[0], days(40)[-1])
    return c.correlate(series, [window], min_observations=min_observations)[0].fingerprint


def test_identical_inputs_give_identical_fingerprints() -> None:
    a, b = make(n=40, seed=5), make(n=40, seed=5)
    assert fingerprint_of(a) == fingerprint_of(b)
    assert len(fingerprint_of(a)) == 64


def test_fingerprint_ignores_symbol_and_window_order() -> None:
    series = make(n=40, seed=5)
    reordered = {k: series[k] for k in reversed(sorted(series))}
    assert fingerprint_of(series) == fingerprint_of(reordered)
    first, second = Window(days(40)[0], days(40)[19]), Window(days(40)[10], days(40)[39])
    forward = c.correlate(series, [first, second], min_observations=5)
    backward = c.correlate(series, [second, first], min_observations=5)
    assert [m.fingerprint for m in forward] == [m.fingerprint for m in reversed(backward)]
    assert forward[0].fingerprint != forward[1].fingerprint


def test_any_change_to_a_value_a_source_a_session_or_a_bound_changes_it() -> None:
    base = fingerprint_of(make(n=40, seed=5))
    value = make(n=40, seed=5)
    value["id2"][days(40)[17]] = Observation(value["id2"][days(40)[17]].value + 1e-12, "h217")
    assert fingerprint_of(value) != base

    corrected = make(n=40, seed=5)
    one = corrected["id0"][days(40)[3]]
    corrected["id0"][days(40)[3]] = Observation(one.value, "revision-2")
    assert fingerprint_of(corrected) != base

    fewer = make(n=40, seed=5)
    del fewer["id3"][days(40)[8]]
    assert fingerprint_of(fewer) != base

    series = make(n=40, seed=5)
    shifted = c.correlate(series, [Window(days(40)[0], days(40)[-2])])[0].fingerprint
    assert shifted != base
    assert fingerprint_of(series, min_observations=21) != base


def test_data_outside_the_window_does_not_change_the_fingerprint() -> None:
    series = make(n=60, seed=5)
    window = Window(days(60)[0], days(60)[39])
    before = c.correlate(series, [window])[0].fingerprint
    series["id1"][days(60)[50]] = Observation(0.5, "later")
    assert c.correlate(series, [window])[0].fingerprint == before
