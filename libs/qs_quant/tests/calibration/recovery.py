"""The parameter-recovery study (Lane C guide §7.5), shared by the CI test (10
replications) and the full study script (50 replications)."""

import math
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from qs_quant.calibration import FitResult, fit_gbm, fit_merton, fit_ou
from tests.calibration import simulate as sim

N_GBM_OU = 2_520
N_MERTON = 5_000
COVERAGE = 0.85
LOOSE_COVERAGE = 0.80
LOOSE = {("merton", "lam"), ("merton", "sigma_j")}


@dataclass(frozen=True)
class ParameterRecovery:
    model: str
    name: str
    true: float
    mean_estimate: float
    mean_se: float
    coverage: float  # share of replications with true in estimate +- 2 SE
    standardised_bias: float  # mean(estimate - true) / mean(SE)
    required_coverage: float

    @property
    def passes(self) -> bool:
        return self.coverage >= self.required_coverage and abs(self.standardised_bias) < 1


def _sample(model: str, replication: int) -> FitResult:
    g = sim.rng(model, replication)
    if model == "gbm":
        return fit_gbm(sim.gbm_log_returns(g, N_GBM_OU, **sim.GBM_TRUE))
    if model == "ou":
        return fit_ou(sim.ou_log_prices(g, N_GBM_OU, **sim.OU_TRUE))
    return fit_merton(sim.merton_log_returns(g, N_MERTON, **sim.MERTON_TRUE))


TRUTH: dict[str, dict[str, float]] = {
    "gbm": sim.GBM_TRUE,
    "ou": sim.OU_TRUE,
    "merton": sim.MERTON_TRUE,
}


def recover(
    model: str, replications: int, fit: Callable[[str, int], FitResult] = _sample
) -> list[ParameterRecovery]:
    """Fit ``replications`` simulated samples and summarise each parameter."""
    fits = [fit(model, rep) for rep in range(replications)]
    refused = [f.refusal_reason for f in fits if f.refused]
    if refused:
        raise AssertionError(f"{model}: {len(refused)} replications refused, e.g. {refused[0]}")
    out = []
    for name, true in TRUTH[model].items():
        est = np.array([f.params[name] for f in fits])
        se = np.array([f.std_errors[name] for f in fits])
        if not np.all(np.isfinite(se)):
            raise AssertionError(f"{model}.{name}: a standard error is not finite")
        mean_se = float(np.mean(se))
        out.append(
            ParameterRecovery(
                model=model,
                name=name,
                true=true,
                mean_estimate=float(np.mean(est)),
                mean_se=mean_se,
                coverage=float(np.mean(np.abs(est - true) <= 2 * se)),
                standardised_bias=float(np.mean(est - true)) / mean_se,
                required_coverage=LOOSE_COVERAGE if (model, name) in LOOSE else COVERAGE,
            )
        )
    return out


def table(rows: list[ParameterRecovery], replications: int) -> str:
    """The results as a Markdown table."""
    lines = [
        "| Model | Parameter | True | Mean estimate | Mean SE "
        f"| Coverage (+-2 SE, {replications} reps) | Required | Standardised bias | Pass |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row.model} | {row.name} | {row.true:.4g} | {row.mean_estimate:.4g} | "
            f"{row.mean_se:.3g} | {row.coverage:.0%} | {row.required_coverage:.0%} | "
            f"{row.standardised_bias:+.2f} | {'yes' if row.passes else 'NO'} |"
        )
    return "\n".join(lines)


__all__ = ["ParameterRecovery", "math", "recover", "table"]
