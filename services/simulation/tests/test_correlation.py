"""B-FR-10, B-NFR-06: correlation validation, PSD repair and its record."""

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.extra import numpy as hnp

from qs_simulation.domain.correlation import (
    EIGENVALUE_FLOOR,
    correlate,
    correlation_factor,
    repair_psd,
)

VALID = np.array([[1.0, 0.6, 0.3], [0.6, 1.0, -0.2], [0.3, -0.2, 1.0]])
NOT_PSD = np.array([[1.0, 0.9, -0.9], [0.9, 1.0, 0.9], [-0.9, 0.9, 1.0]])


def test_a_valid_matrix_is_returned_unchanged_with_no_repair() -> None:
    fixed, record = repair_psd(VALID)
    np.testing.assert_array_equal(fixed, VALID)
    assert not record.applied and record.frobenius_change == 0.0
    assert record.min_eigenvalue_before > EIGENVALUE_FLOOR


def test_a_non_psd_matrix_is_repaired_and_recorded() -> None:
    assert np.linalg.eigvalsh(NOT_PSD).min() < 0  # the input really is invalid
    fixed, record = repair_psd(NOT_PSD)
    assert record.applied and record.min_eigenvalue_before < 0 and record.frobenius_change > 0
    np.testing.assert_allclose(np.diag(fixed), 1.0, atol=1e-12)
    np.testing.assert_allclose(fixed, fixed.T, atol=1e-15)
    assert np.linalg.eigvalsh(fixed).min() > 0
    np.linalg.cholesky(fixed)  # does not raise


def test_the_factor_reproduces_the_repaired_matrix() -> None:
    factor, record = correlation_factor(NOT_PSD)
    fixed, _ = repair_psd(NOT_PSD)
    np.testing.assert_allclose(factor @ factor.T, fixed, atol=1e-12)
    assert record.applied
    assert np.allclose(factor, np.tril(factor))


def test_correlate_gives_the_target_correlation() -> None:
    eps = np.random.default_rng(21).standard_normal((200_000, 3))
    z = correlate(eps, correlation_factor(VALID)[0])
    assert np.abs(np.corrcoef(z, rowvar=False) - VALID).max() < 0.01


@pytest.mark.parametrize(
    ("matrix", "words"),
    [
        (np.ones((2, 3)), "square"),
        (np.array([[1.0, 0.5], [0.4, 1.0]]), "symmetric"),
        (np.array([[1.0, 0.5], [0.5, 0.9]]), "unit diagonal"),
        (np.array([[1.0, 1.5], [1.5, 1.0]]), r"\[-1, 1\]"),
        (np.array([[1.0, np.nan], [np.nan, 1.0]]), "finite"),
    ],
)
def test_invalid_matrices_are_refused_with_the_reason(matrix: np.ndarray, words: str) -> None:
    with pytest.raises(ValueError, match=words):
        repair_psd(matrix)


@st.composite
def symmetric_unit_diagonal(draw: st.DrawFn) -> np.ndarray:
    n = draw(st.integers(2, 6))
    raw = draw(hnp.arrays(np.float64, (n, n), elements=st.floats(-1, 1, allow_nan=False)))
    upper = np.triu(raw, 1)
    return upper + upper.T + np.eye(n)


@settings(max_examples=200, deadline=None)
@given(symmetric_unit_diagonal())
def test_repair_always_yields_a_usable_correlation_matrix(matrix: np.ndarray) -> None:
    fixed, record = repair_psd(matrix)
    assert record.applied == (record.min_eigenvalue_before < EIGENVALUE_FLOOR)
    np.testing.assert_allclose(np.diag(fixed), 1.0, atol=1e-10)
    np.testing.assert_allclose(fixed, fixed.T, atol=1e-12)
    np.linalg.cholesky(fixed)  # positive definite
