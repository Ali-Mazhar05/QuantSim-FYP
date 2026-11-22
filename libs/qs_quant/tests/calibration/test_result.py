"""FitResult invariants and the refusal codes Lane B maps to 422 problems."""

import dataclasses
import math

import pytest

from qs_quant.calibration import REFUSAL_CODES, FitResult, refusal_code
from qs_quant.calibration.result import refused


def test_codes_are_the_documented_five() -> None:
    assert REFUSAL_CODES == {
        "invalid_input",
        "insufficient_history",
        "constant_series",
        "not_mean_reverting",
        "numerical_failure",
    }


@pytest.mark.parametrize("code", sorted(REFUSAL_CODES))
def test_a_refusal_starts_with_its_code(code: str) -> None:
    fit = refused("gbm", 3, code, "because")
    assert fit.refusal_reason == f"{code}: because"
    assert refusal_code(fit) == code
    assert fit.refused and not fit.converged
    assert math.isnan(fit.log_likelihood) and math.isnan(fit.aic)


def test_an_unknown_code_is_a_programming_error() -> None:
    with pytest.raises(ValueError, match="unknown refusal code"):
        refused("gbm", 0, "oops", "x")


def test_a_fit_without_a_refusal_has_no_code() -> None:
    fit = FitResult(
        "gbm", {"mu": 0.1, "sigma": 0.2}, {"mu": 0.01, "sigma": 0.001}, 1.0, 2.0, 60, True
    )
    assert refusal_code(fit) is None and not fit.refused


def test_the_result_is_frozen() -> None:
    fit = refused("ou", 0, "invalid_input", "x")
    with pytest.raises(dataclasses.FrozenInstanceError):
        fit.converged = True  # type: ignore[misc]
