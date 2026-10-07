// Registry describing the three risk lenses a user can run.
// Every risk view reads module metadata from here so that a run of one, two,
// or all three modules renders from the same shape.

import type { RiskModuleDefinition, RiskModuleKey } from '../../types'
import { ML_PREDICTION, STRESS_RESULT, TDA_ANALYSIS } from './data'

export const RISK_MODULE_ORDER: RiskModuleKey[] = ['stress', 'tda', 'ml']

export const RISK_MODULES: Record<RiskModuleKey, RiskModuleDefinition> = {
  stress: {
    key: 'stress',
    title: 'Stress Testing',
    short: 'Stress',
    question: 'What if disaster strikes?',
    route: '/risk/stress-testing',
    weight: 31,
    score: STRESS_RESULT.score,
    level: STRESS_RESULT.level,
    completedAt: STRESS_RESULT.completedAt,
    driverLabel: 'Correlation Convergence (Stress)',
    metrics: [
      { label: 'Maximum Loss', value: `${STRESS_RESULT.maxLossPct}%`, tone: 'negative' },
      { label: 'Recovery Time', value: `${STRESS_RESULT.recoveryDays} days` },
    ],
    explanation: [
      'Under the correlated-failure scenario, portfolio losses increase because several large positions become exposed to the same market movement.',
    ],
  },
  tda: {
    key: 'tda',
    title: 'TDA Analysis',
    short: 'TDA',
    question: 'Is market structure changing?',
    route: '/risk/tda-analysis',
    weight: 38,
    score: TDA_ANALYSIS.score,
    level: TDA_ANALYSIS.level,
    completedAt: TDA_ANALYSIS.completedAt,
    driverLabel: 'Structural Change (TDA)',
    metrics: [
      { label: 'Shift Detected', value: TDA_ANALYSIS.shiftDetectedAt, tone: 'negative' },
      { label: 'Window', value: `${TDA_ANALYSIS.windowDays} days` },
    ],
    explanation: [
      'Market structure has become significantly more interconnected over the latest rolling windows.',
      'This reduces diversification and indicates a transition toward a more synchronized market state.',
    ],
  },
  ml: {
    key: 'ml',
    title: 'ML Prediction',
    short: 'ML',
    question: 'What does the data suggest?',
    route: '/ml/predictions',
    weight: 22,
    score: ML_PREDICTION.score,
    level: ML_PREDICTION.level,
    completedAt: ML_PREDICTION.completedAt,
    driverLabel: 'Drawdown Probability (ML)',
    metrics: [
      { label: 'Drawdown Probability', value: `${ML_PREDICTION.drawdownProbabilityPct}%`, tone: 'negative' },
      { label: 'Market Regime', value: ML_PREDICTION.marketRegime, tone: 'negative' },
    ],
    explanation: [
      'The predicted drawdown probability increased primarily because correlation changes and volatility have moved sharply higher.',
    ],
  },
}

export function sortModuleKeys(keys: RiskModuleKey[]): RiskModuleKey[] {
  return RISK_MODULE_ORDER.filter((k) => keys.includes(k))
}

export function moduleNameList(keys: RiskModuleKey[]): string {
  const names = sortModuleKeys(keys).map((k) => RISK_MODULES[k].title)
  if (names.length <= 1) return names.join('')
  return `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`
}
