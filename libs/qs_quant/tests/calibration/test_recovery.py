"""Parameter recovery in CI (Lane C guide §7.5). The true values lie within +-2 SE in at
least 85% of replications (80% for lam and sigma_j) and the standardised bias
mean(estimate - true) / mean(SE) is below 1 in absolute value.

GBM and OU are cheap, so CI runs the full 50 replications of the study
(studies/recovery_study.py), on the same seeded streams. Merton runs the guide's reduced
10 replications as a regression guard; at 10 samples an 85% coverage bar is a coarse
check (a true 95% coverage gives 8 or fewer hits out of 10 about 7% of the time), so the
50-replication study is the evidence for Merton."""

import pytest

from tests.calibration.recovery import recover, table

REPLICATIONS = {"gbm": 50, "ou": 50, "merton": 10}


@pytest.mark.parametrize("model", list(REPLICATIONS))
def test_parameters_are_recovered(model: str) -> None:
    rows = recover(model, REPLICATIONS[model])
    assert all(row.passes for row in rows), "\n" + table(rows, REPLICATIONS[model])
