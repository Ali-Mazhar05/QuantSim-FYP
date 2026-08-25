// Centralized mock data layer. Every page in the POC reads from here so the
// same simulation, portfolio and risk numbers stay consistent across screens.
// Values are illustrative demo data only — see docs referenced in the repo
// for the real architecture this POC represents.

import type {
  Alert,
  AuditEvent,
  Calibration,
  CompositeRisk,
  Instrument,
  MLModelDef,
  MLPrediction,
  MarketEnvironment,
  Portfolio,
  ReportDef,
  Strategy,
  StressScenario,
  StressTestResult,
  SystemEvent,
  TDAAnalysis,
  TradeEvent,
  UserAccount,
} from '../../types'
import {
  correlationToDistance,
  generateCorrelationMatrix,
  generateLandscapeCurves,
  generatePersistencePoints,
} from './generators'

export const INSTRUMENTS: Instrument[] = [
  { symbol: 'AAPL', name: 'Apple Inc.', sector: 'Technology', price: 214.32, changePct: 0.62 },
  { symbol: 'MSFT', name: 'Microsoft Corp.', sector: 'Technology', price: 521.4, changePct: 1.14 },
  { symbol: 'NVDA', name: 'NVIDIA Corp.', sector: 'Semiconductors', price: 141.2, changePct: -0.85 },
  { symbol: 'AMZN', name: 'Amazon.com Inc.', sector: 'Consumer Discretionary', price: 231.77, changePct: 0.31 },
  { symbol: 'GOOGL', name: 'Alphabet Inc.', sector: 'Communication Services', price: 189.44, changePct: 0.48 },
  { symbol: 'META', name: 'Meta Platforms Inc.', sector: 'Communication Services', price: 712.05, changePct: -0.22 },
  { symbol: 'TSLA', name: 'Tesla Inc.', sector: 'Consumer Discretionary', price: 268.91, changePct: 2.03 },
]

export const PORTFOLIO_ASSETS = ['AAPL', 'MSFT', 'NVDA', 'AMZN', 'GOOGL']

export const MARKET_ENVIRONMENTS: MarketEnvironment[] = [
  {
    id: 'env-001',
    name: 'US Technology Basket',
    type: 'Synthetic Market',
    universe: 'US Technology Basket',
    instruments: PORTFOLIO_ASSETS,
    start: '2025-01-01',
    end: '2026-06-30',
    frequency: 'Daily',
    status: 'Active',
  },
  {
    id: 'env-002',
    name: 'US Equities — Historical Replay',
    type: 'Historical Replay',
    universe: 'S&P 500 Subset',
    instruments: ['AAPL', 'MSFT', 'AMZN', 'META', 'TSLA'],
    start: '2023-01-01',
    end: '2025-12-31',
    frequency: 'Daily',
    status: 'Ready',
  },
  {
    id: 'env-003',
    name: 'Semiconductor Sector Replay',
    type: 'Historical Replay',
    universe: 'Semiconductor Basket',
    instruments: ['NVDA', 'AAPL', 'MSFT'],
    start: '2024-01-01',
    end: '2026-01-01',
    frequency: 'Daily',
    status: 'Draft',
  },
]

export const CALIBRATIONS: Calibration[] = [
  { id: 'cal-aapl-2025', instrument: 'AAPL', label: 'AAPL — 2025 Historical', drift: 0.084, volatility: 0.231, windowDays: 252, status: 'Valid' },
  { id: 'cal-msft-2025', instrument: 'MSFT', label: 'MSFT — 2025 Historical', drift: 0.091, volatility: 0.198, windowDays: 252, status: 'Valid' },
  { id: 'cal-nvda-2025', instrument: 'NVDA', label: 'NVDA — 2025 Historical', drift: 0.152, volatility: 0.412, windowDays: 252, status: 'Valid' },
  { id: 'cal-amzn-2024', instrument: 'AMZN', label: 'AMZN — 2024 Historical', drift: 0.071, volatility: 0.264, windowDays: 180, status: 'Stale' },
]

export const STRATEGIES: Strategy[] = [
  {
    id: 'strat-momentum-1',
    name: 'Momentum Strategy',
    description: [
      'Buy assets with positive 20-day momentum.',
      'Rebalance weekly.',
      'Maximum position: 25%.',
    ],
    rebalance: 'Weekly',
    maxPosition: 25,
  },
  {
    id: 'strat-value-1',
    name: 'Value Strategy',
    description: [
      'Buy assets trading below their trailing 200-day average valuation.',
      'Rebalance monthly.',
      'Maximum position: 20%.',
    ],
    rebalance: 'Monthly',
    maxPosition: 20,
  },
  {
    id: 'strat-pairs-1',
    name: 'Pairs Strategy',
    description: [
      'Trade the spread between two historically correlated instruments.',
      'Rebalance daily.',
      'Maximum position: 15%.',
    ],
    rebalance: 'Daily',
    maxPosition: 15,
  },
]

export const STRATEGY: Strategy = STRATEGIES[0]

export const PORTFOLIO: Portfolio = {
  id: 'pf-1042',
  name: 'Momentum Strategy — Run #1042',
  strategyId: STRATEGY.id,
  simulationId: 'sim-1042',
  startingCapital: 1_000_000,
  baseCurrency: 'USD',
  positions: [
    { symbol: 'AAPL', weight: 24 },
    { symbol: 'MSFT', weight: 21 },
    { symbol: 'NVDA', weight: 25 },
    { symbol: 'AMZN', weight: 15 },
    { symbol: 'GOOGL', weight: 15 },
  ],
  transactionCostPct: 0.05,
  slippagePct: 0.02,
  currentValue: 1_083_421,
  returnPct: 8.34,
  volatilityPct: 18.2,
  variancePct: 3.31,
  maxDrawdownPct: -11.7,
}

export const TRADE_EVENTS: TradeEvent[] = [
  { time: '09:31:02', event: 'BUY', instrument: 'NVDA', quantity: 100, price: 141.2, status: 'Filled' },
  { time: '09:34:17', event: 'BUY', instrument: 'MSFT', quantity: 50, price: 521.4, status: 'Filled' },
  { time: '10:12:08', event: 'SELL', instrument: 'AAPL', quantity: 30, price: 214.1, status: 'Filled' },
  { time: '10:47:51', event: 'BUY', instrument: 'AMZN', quantity: 65, price: 231.77, status: 'Filled' },
  { time: '11:22:36', event: 'BUY', instrument: 'GOOGL', quantity: 80, price: 189.44, status: 'Filled' },
  { time: '12:05:14', event: 'SELL', instrument: 'NVDA', quantity: 20, price: 143.85, status: 'Filled' },
  { time: '13:41:29', event: 'BUY', instrument: 'MSFT', quantity: 25, price: 524.1, status: 'Filled' },
  { time: '14:18:02', event: 'SELL', instrument: 'GOOGL', quantity: 15, price: 191.02, status: 'Filled' },
  { time: '15:02:47', event: 'BUY', instrument: 'AAPL', quantity: 40, price: 215.6, status: 'Filled' },
  { time: '15:52:11', event: 'BUY', instrument: 'NVDA', quantity: 55, price: 144.9, status: 'Filled' },
]

export const STRESS_SCENARIOS: StressScenario[] = [
  { id: 'flash-crash', name: 'Flash Crash', description: 'A sudden, sharp decline in prices across the portfolio within minutes, followed by partial recovery.' },
  { id: 'liquidity-shock', name: 'Liquidity Shock', description: 'Bid-ask spreads widen sharply and market depth collapses, increasing execution costs.' },
  { id: 'volatility-spike', name: 'Volatility Spike', description: 'Realized and implied volatility surge across the universe, compressing risk-adjusted returns.' },
  { id: 'sector-collapse', name: 'Sector Collapse', description: 'A concentrated drawdown in a single sector propagates into portfolio-level losses.' },
  { id: 'correlated-failure', name: 'Correlated Failure', description: 'Diversification collapses as asset correlations converge toward 1.' },
]

export const STRESS_RESULT: StressTestResult = {
  id: 'stress-1042',
  scenarioId: 'correlated-failure',
  portfolioId: PORTFOLIO.id,
  maxLossPct: -21.4,
  var: -18.7,
  cvar: -25.1,
  recoveryDays: 47,
  contribution: [
    { symbol: 'NVDA', pct: 34 },
    { symbol: 'AAPL', pct: 24 },
    { symbol: 'MSFT', pct: 20 },
    { symbol: 'AMZN', pct: 13 },
    { symbol: 'GOOGL', pct: 9 },
  ],
  score: 72,
  level: 'ELEVATED',
  completedAt: '16:21:44',
}

const CORR_SEED = 7331
const correlationMatrix = generateCorrelationMatrix(PORTFOLIO_ASSETS, CORR_SEED, 0.55)

export const TDA_ANALYSIS: TDAAnalysis = {
  id: 'tda-1042',
  portfolioId: PORTFOLIO.id,
  windowDays: 60,
  stepDays: 5,
  assets: PORTFOLIO_ASSETS,
  correlationMatrix,
  distanceMatrix: correlationToDistance(correlationMatrix),
  persistencePoints: [
    ...generatePersistencePoints(101, 6, 0, 0.9),
    ...generatePersistencePoints(202, 3, 1, 0.6),
  ],
  landscapeCurves: generateLandscapeCurves(303, 4, 80),
  score: 84,
  level: 'HIGH',
  shiftDetectedAt: '2026-06-24',
  completedAt: '16:22:03',
}

export const ML_PREDICTION: MLPrediction = {
  id: 'ml-1042',
  modelName: 'Portfolio Risk Model',
  modelVersion: 'v1.4',
  portfolioId: PORTFOLIO.id,
  volatilityForecastPct: 27.4,
  drawdownProbabilityPct: 63,
  marketRegime: 'Stress',
  regimeTimeline: ['Calm', 'Calm', 'Transition', 'Stress'],
  portfolioHealth: 61,
  confidencePct: 87,
  featureImportance: [
    { feature: 'Rolling Volatility', impact: 9 },
    { feature: 'Correlation Change', impact: 8 },
    { feature: 'Drawdown', impact: 7 },
    { feature: 'Momentum', impact: 4 },
    { feature: 'Volume', impact: 3 },
  ],
  score: 68,
  level: 'ELEVATED',
  completedAt: '16:22:16',
}

export const COMPOSITE_RISK: CompositeRisk = {
  id: 'composite-1042',
  portfolioId: PORTFOLIO.id,
  stressScore: STRESS_RESULT.score,
  tdaScore: TDA_ANALYSIS.score,
  mlScore: ML_PREDICTION.score,
  compositeScore: 76,
  level: 'HIGH',
  interpretation: [
    'The portfolio is currently exposed to elevated systemic risk.',
    'The strongest contributor is the structural change detected by the topology analysis.',
    'Stress testing confirms that diversification benefits deteriorate significantly under correlation convergence.',
    'ML independently identifies an elevated drawdown probability.',
  ],
  drivers: [
    { label: 'Structural Change (TDA)', pct: 38 },
    { label: 'Correlation Convergence (Stress)', pct: 31 },
    { label: 'Drawdown Probability (ML)', pct: 22 },
    { label: 'Volatility Trend', pct: 9 },
  ],
  completedAt: '16:22:21',
}

export const ALERT: Alert = {
  id: 'alert-1042-1',
  title: 'RISK ALERT',
  message: 'Structural market change detected',
  detail: 'Topology risk crossed threshold: 75 → 82',
  severity: 'HIGH',
  source: 'TDA Analysis',
  portfolioId: PORTFOLIO.id,
  status: 'Active',
  createdAt: '16:22:21',
}

export const AUDIT_EVENTS: AuditEvent[] = [
  { id: 'a1', timestamp: '16:20:01', user: 'Quant', service: 'Simulation', action: 'Simulation #1042 created', severity: 'Info', detail: 'GBM model, AAPL, 10,000 paths, 252 steps.' },
  { id: 'a2', timestamp: '16:20:07', user: 'Quant', service: 'Simulation', action: 'Simulation started', severity: 'Info', detail: '4 workers assigned.' },
  { id: 'a3', timestamp: '16:20:31', user: 'System', service: 'Simulation', action: 'Simulation completed', severity: 'Info', detail: '10,000 / 10,000 paths generated.' },
  { id: 'a4', timestamp: '16:21:02', user: 'Quant', service: 'Trading', action: 'Portfolio created', severity: 'Info', detail: 'Momentum Strategy, $1,000,000 starting capital.' },
  { id: 'a5', timestamp: '16:21:38', user: 'System', service: 'Trading', action: 'Trading replay completed', severity: 'Info', detail: '10 fills, ending value $1,083,421.' },
  { id: 'a6', timestamp: '16:21:44', user: 'Analyst', service: 'Risk / Stress', action: 'Stress analysis completed', severity: 'Warning', detail: 'Correlated Failure scenario, max loss -21.4%.' },
  { id: 'a7', timestamp: '16:22:03', user: 'Analyst', service: 'Risk / TDA', action: 'TDA analysis completed', severity: 'Warning', detail: 'Topology signal 84 / 100 — HIGH.' },
  { id: 'a8', timestamp: '16:22:16', user: 'System', service: 'Intelligence / ML', action: 'ML prediction generated', severity: 'Warning', detail: 'Drawdown probability 63%, regime Stress.' },
  { id: 'a9', timestamp: '16:22:19', user: 'System', service: 'Explainability', action: 'Explanation generated', severity: 'Info', detail: '3 explanation sections produced.' },
  { id: 'a10', timestamp: '16:22:21', user: 'System', service: 'Risk / Composite', action: 'Risk alert triggered', severity: 'Critical', detail: 'Composite risk 76 / 100 — HIGH.' },
]

export const SYSTEM_EVENTS: SystemEvent[] = [
  { id: 'e1', type: 'SIMULATION_STARTED', timestamp: '16:20:07', detail: 'Simulation #1042 queued to 4 workers.' },
  { id: 'e2', type: 'SIMULATION_COMPLETED', timestamp: '16:20:31', detail: 'Monte Carlo ensemble generated.' },
  { id: 'e3', type: 'PORTFOLIO_CREATED', timestamp: '16:21:02', detail: 'Momentum Strategy portfolio created.' },
  { id: 'e4', type: 'TRADING_COMPLETED', timestamp: '16:21:38', detail: 'Trade replay finished with 10 fills.' },
  { id: 'e5', type: 'STRESS_TEST_COMPLETED', timestamp: '16:21:44', detail: 'Correlated Failure scenario evaluated.' },
  { id: 'e6', type: 'TDA_ANALYSIS_COMPLETED', timestamp: '16:22:03', detail: 'Persistence landscape generated.' },
  { id: 'e7', type: 'ML_PREDICTION_CREATED', timestamp: '16:22:16', detail: 'Portfolio Risk Model v1.4 scored the portfolio.' },
  { id: 'e8', type: 'EXPLANATION_GENERATED', timestamp: '16:22:19', detail: 'Explainability report assembled.' },
  { id: 'e9', type: 'RISK_SCORE_UPDATED', timestamp: '16:22:21', detail: 'Composite risk set to 76 / 100.' },
  { id: 'e10', type: 'ALERT_TRIGGERED', timestamp: '16:22:21', detail: 'High-severity alert raised on Momentum Strategy.' },
]

export const REPORTS: ReportDef[] = [
  { id: 'rep-portfolio', name: 'Portfolio Risk Report', description: 'Position-level risk exposure and concentration summary.', category: 'Portfolio' },
  { id: 'rep-simulation', name: 'Simulation Report', description: 'Monte Carlo ensemble summary and terminal distribution.', category: 'Simulation' },
  { id: 'rep-stress', name: 'Stress Test Report', description: 'Scenario losses, recovery profile and contribution breakdown.', category: 'Stress' },
  { id: 'rep-tda', name: 'TDA Analysis Report', description: 'Topological structure signal and persistence summary.', category: 'TDA' },
  { id: 'rep-ml', name: 'ML Prediction Report', description: 'Model forecasts, regime classification and feature attribution.', category: 'ML' },
  { id: 'rep-composite', name: 'Composite Risk Report', description: 'Blended risk score across all three analytical lenses.', category: 'Composite' },
]

export const ML_MODELS: MLModelDef[] = [
  { id: 'model-1', name: 'Portfolio Risk Model', version: 'v1.4', task: 'Risk classification', status: 'Production', accuracy: 91.2, lastTrained: '2026-06-18' },
  { id: 'model-2', name: 'Drawdown Probability Model', version: 'v2.1', task: 'Probability regression', status: 'Production', accuracy: 88.7, lastTrained: '2026-06-12' },
  { id: 'model-3', name: 'Regime Classifier', version: 'v1.0', task: 'Sequence classification', status: 'Staging', accuracy: 84.3, lastTrained: '2026-05-29' },
  { id: 'model-4', name: 'Volatility Forecaster', version: 'v0.9', task: 'Time-series forecasting', status: 'Archived', accuracy: 79.5, lastTrained: '2026-03-02' },
]

export const USERS: UserAccount[] = [
  { id: 'u1', name: 'Awais', email: 'Awais@powerbanclending.com', role: 'Quant', status: 'Active', lastActive: '2026-08-25 16:22' },
  { id: 'u2', name: 'M. Reyes', email: 'm.reyes@quantsim.demo', role: 'Analyst', status: 'Active', lastActive: '2026-08-25 14:03' },
  { id: 'u3', name: 'J. Okafor', email: 'j.okafor@quantsim.demo', role: 'Viewer', status: 'Active', lastActive: '2026-08-24 09:41' },
  { id: 'u4', name: 'System Admin', email: 'admin@quantsim.demo', role: 'Admin', status: 'Active', lastActive: '2026-08-23 18:12' },
  { id: 'u5', name: 'S. Tanaka', email: 's.tanaka@quantsim.demo', role: 'Analyst', status: 'Invited', lastActive: '—' },
]
