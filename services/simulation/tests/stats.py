"""Standardised errors for the generator tests: how many standard errors a sample statistic is
from its theoretical value. A correct generator stays within 3 (ADR 02, B-NFR-06)."""

import numpy as np
from numpy.typing import NDArray

Array = NDArray[np.float64]


def z_mean(sample: Array, expected: float | Array) -> Array:
    """(sample mean - expected) / standard error of the mean, per column of ``sample``."""
    n = sample.shape[0]
    return np.asarray((sample.mean(axis=0) - expected) / (sample.std(axis=0, ddof=1) / np.sqrt(n)))


def z_variance(sample: Array, expected: float | Array) -> Array:
    """(sample variance - expected) / standard error of the variance, per column.

    The standard error uses the sample's own fourth moment, so it is right for non-normal
    samples too (the Merton log price has fat tails).
    """
    n = sample.shape[0]
    centred = sample - sample.mean(axis=0)
    m2 = (centred**2).mean(axis=0)
    m4 = (centred**4).mean(axis=0)
    return np.asarray((m2 - expected) / np.sqrt((m4 - m2**2) / n))
