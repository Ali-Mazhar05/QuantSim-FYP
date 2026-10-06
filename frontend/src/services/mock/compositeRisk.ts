// Derives the composite risk score from whichever risk modules were actually run.
// Weights are renormalized over the modules present, so a one-module run reports
// that module's own score and a three-module run reproduces the demo scenario.

import { scoreToLevel } from '../../components/status/RiskBadge'
import type { CompositeBreakdownRow, CompositeRisk, RiskDriver, RiskModuleKey } from '../../types'
import { PORTFOLIO } from './data'
import { RISK_MODULES, moduleNameList, sortModuleKeys } from './riskModules'

// Share of the driver chart reserved for the signal that is not attributable to
// a single module. The remainder is split across the modules that ran.
const SHARED_DRIVER_PCT = 9

const LEAD_INTERPRETATION: Record<string, string> = {
  SEVERE: 'The portfolio is currently exposed to severe systemic risk.',
  HIGH: 'The portfolio is currently exposed to elevated systemic risk.',
  ELEVATED: 'The portfolio is currently exposed to elevated systemic risk.',
  MODERATE: 'The portfolio is currently exposed to moderate systemic risk.',
  LOW: 'The portfolio is currently operating within its normal risk range.',
}

const MODULE_INTERPRETATION: Record<RiskModuleKey, { leading: string; supporting: string }> = {
  stress: {
    leading: 'The strongest contributor is the loss concentration exposed by stress testing.',
    supporting:
      'Stress testing confirms that diversification benefits deteriorate significantly under correlation convergence.',
  },
  tda: {
    leading: 'The strongest contributor is the structural change detected by the topology analysis.',
    supporting:
      'Topology analysis detects a structural change in how the portfolio assets move together.',
  },
  ml: {
    leading: 'The strongest contributor is the drawdown probability predicted by the ML model.',
    supporting: 'ML independently identifies an elevated drawdown probability.',
  },
}

export function buildCompositeRisk(keys: RiskModuleKey[]): CompositeRisk | null {
  const modules = sortModuleKeys(keys)
  if (modules.length === 0) return null

  const defs = modules.map((k) => RISK_MODULES[k])
  const weightTotal = defs.reduce((sum, d) => sum + d.weight, 0)
  const weightedTotal = defs.reduce((sum, d) => sum + d.weight * d.score, 0)
  const compositeScore = Math.round(weightedTotal / weightTotal)
  const level = scoreToLevel(compositeScore)

  const breakdown: CompositeBreakdownRow[] = defs.map((d) => ({
    key: d.key,
    title: d.title,
    short: d.short,
    score: d.score,
    level: d.level,
    weightPct: Math.round((d.weight / weightTotal) * 100),
    contributionPct: Math.round(((d.weight * d.score) / weightedTotal) * 100),
  }))

  const leadingKey = defs.reduce((top, d) => (d.weight * d.score > top.weight * top.score ? d : top)).key

  const interpretation = [
    LEAD_INTERPRETATION[level],
    ...modules.map((k) =>
      k === leadingKey && modules.length > 1
        ? MODULE_INTERPRETATION[k].leading
        : MODULE_INTERPRETATION[k].supporting,
    ),
  ]
  if (modules.length === 1) {
    interpretation.push(
      'Only one risk lens was run, so the composite score is that lens on its own. Running the remaining lenses would widen the coverage.',
    )
  }

  const drivers = buildDrivers(defs.map((d) => ({ label: d.driverLabel, weight: d.weight })), weightTotal)

  const coverageNote =
    modules.length === 3
      ? 'Composite computed from all 3 risk lenses.'
      : `Composite computed from ${modules.length} of 3 risk lenses — ${moduleNameList(modules)}.`

  return {
    id: 'composite-1042',
    portfolioId: PORTFOLIO.id,
    modules,
    breakdown,
    compositeScore,
    level,
    coverageNote,
    interpretation,
    drivers,
    completedAt: defs.map((d) => d.completedAt).sort().slice(-1)[0],
  }
}

function buildDrivers(parts: { label: string; weight: number }[], weightTotal: number): RiskDriver[] {
  const share = 100 - SHARED_DRIVER_PCT
  const rows = parts.map((p) => ({ label: p.label, pct: Math.round((p.weight / weightTotal) * share) }))
  // Push any rounding remainder onto the largest row so the chart still sums to 100.
  const drift = share - rows.reduce((sum, r) => sum + r.pct, 0)
  if (drift !== 0) {
    const largest = rows.reduce((top, r) => (r.pct > top.pct ? r : top))
    largest.pct += drift
  }
  rows.sort((a, b) => b.pct - a.pct)
  return [...rows, { label: 'Volatility Trend', pct: SHARED_DRIVER_PCT }]
}
