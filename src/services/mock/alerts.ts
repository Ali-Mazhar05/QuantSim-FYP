// Risk alerts are generated from the lenses the user actually ran, once the
// analysis reaches the risk hub. Nothing here fires on its own: the demo store
// records which modules the alerts were raised for and which were dismissed.

import type { Alert, CompositeRisk, RiskModuleKey } from '../../types'
import { ML_PREDICTION, PORTFOLIO, STRESS_RESULT, TDA_ANALYSIS } from './data'
import { RISK_MODULES } from './riskModules'

// A lens only raises an alert once its own score clears this line.
const ALERT_THRESHOLD = 50

const MODULE_ALERTS: Record<RiskModuleKey, Pick<Alert, 'title' | 'message' | 'detail' | 'source'>> = {
  stress: {
    title: 'STRESS ALERT',
    message: 'Portfolio loss exceeds tolerance under stress',
    detail: `Correlated Failure scenario: max loss ${STRESS_RESULT.maxLossPct}%, recovery ${STRESS_RESULT.recoveryDays} days`,
    source: 'Stress Testing',
  },
  tda: {
    title: 'RISK ALERT',
    message: 'Structural market change detected',
    detail: `Topology risk crossed threshold: 75 to ${TDA_ANALYSIS.score}`,
    source: 'TDA Analysis',
  },
  ml: {
    title: 'ML ALERT',
    message: 'Elevated drawdown probability predicted',
    detail: `Drawdown probability ${ML_PREDICTION.drawdownProbabilityPct}% with regime classified as ${ML_PREDICTION.marketRegime}`,
    source: 'ML Prediction',
  },
}

export function buildRiskAlerts(composite: CompositeRisk | null): Alert[] {
  if (!composite) return []

  const alerts: Alert[] = composite.modules
    .filter((key) => RISK_MODULES[key].score >= ALERT_THRESHOLD)
    .map((key) => {
      const mod = RISK_MODULES[key]
      return {
        ...MODULE_ALERTS[key],
        id: `alert-1042-${key}`,
        severity: mod.level,
        portfolioId: PORTFOLIO.id,
        status: 'Active' as const,
        createdAt: mod.completedAt,
        moduleKey: key,
        investigateRoute: mod.route,
      }
    })

  if (composite.modules.length > 1) {
    alerts.push({
      id: 'alert-1042-composite',
      title: 'COMPOSITE RISK ALERT',
      message: `Composite risk is ${composite.level} at ${composite.compositeScore} / 100`,
      detail: composite.coverageNote,
      severity: composite.level,
      source: 'Composite Risk',
      portfolioId: PORTFOLIO.id,
      status: 'Active',
      createdAt: composite.completedAt,
      investigateRoute: '/risk/composite',
    })
  }

  return alerts
}

// Static history so the alerts page has context beyond the current run.
export const ALERT_HISTORY: { title: string; severity: Alert['severity']; time: string }[] = [
  { title: 'Volatility spike detected in NVDA position', severity: 'ELEVATED', time: 'Yesterday 11:02' },
  { title: 'Calibration for AMZN marked stale', severity: 'MODERATE', time: '2 days ago' },
]
