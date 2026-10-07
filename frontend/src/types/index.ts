// Core domain types for the QuantSim POC.
// These mirror the conceptual data model described in the architecture docs,
// but are populated entirely from the mock data layer (src/services/mock).

export type Role = 'Viewer' | 'Analyst' | 'Quant' | 'Admin'

export type RiskLevel = 'LOW' | 'MODERATE' | 'ELEVATED' | 'HIGH' | 'SEVERE'

export interface Instrument {
  symbol: string
  name: string
  sector: string
  price: number
  changePct: number
}

export interface MarketEnvironment {
  id: string
  name: string
  type: 'Historical Replay' | 'Synthetic Market'
  universe: string
  instruments: string[]
  start: string
  end: string
  frequency: 'Daily' | 'Hourly' | 'Tick'
  status: 'Draft' | 'Ready' | 'Active'
}

export type StochasticModel = 'GBM' | 'Jump Diffusion' | 'Ornstein-Uhlenbeck' | 'Regime Switching'

export interface Calibration {
  id: string
  instrument: string
  label: string
  drift: number
  volatility: number
  windowDays: number
  status: 'Valid' | 'Stale' | 'Invalid'
}

export interface SimulationRun {
  id: string
  runNumber: number
  model: StochasticModel
  instrument: string
  calibrationId: string
  paths: number
  steps: number
  confidence: number
  status: 'Configured' | 'Running' | 'Complete' | 'Failed'
  progressPct: number
  startedAt?: string
  completedAt?: string
  terminal: {
    mean: number
    median: number
    p5: number
    p95: number
  }
  riskSummary: {
    var95: number
    cvar95: number
  }
}

export interface Strategy {
  id: string
  name: string
  description: string[]
  rebalance: string
  maxPosition: number
}

export interface Position {
  symbol: string
  weight: number
}

export interface Portfolio {
  id: string
  name: string
  strategyId: string
  simulationId: string
  startingCapital: number
  baseCurrency: string
  positions: Position[]
  transactionCostPct: number
  slippagePct: number
  currentValue: number
  returnPct: number
  volatilityPct: number
  variancePct: number
  maxDrawdownPct: number
}

export interface TradeEvent {
  time: string
  event: 'BUY' | 'SELL'
  instrument: string
  quantity: number
  price: number
  status: 'Filled' | 'Pending' | 'Rejected'
}

export type StressScenarioId =
  | 'flash-crash'
  | 'liquidity-shock'
  | 'volatility-spike'
  | 'sector-collapse'
  | 'correlated-failure'

export interface StressScenario {
  id: StressScenarioId
  name: string
  description: string
}

export interface StressTestResult {
  id: string
  scenarioId: StressScenarioId
  portfolioId: string
  maxLossPct: number
  var: number
  cvar: number
  recoveryDays: number
  contribution: { symbol: string; pct: number }[]
  score: number
  level: RiskLevel
  completedAt: string
}

export interface TDAStageStatus {
  correlation: boolean
  distanceMatrix: boolean
  complex: boolean
  homology: boolean
  landscape: boolean
  signal: boolean
}

export interface TDAAnalysis {
  id: string
  portfolioId: string
  windowDays: number
  stepDays: number
  correlationMatrix: number[][]
  assets: string[]
  distanceMatrix: number[][]
  persistencePoints: { birth: number; death: number; dim: 0 | 1 }[]
  landscapeCurves: number[][]
  score: number
  level: RiskLevel
  shiftDetectedAt: string
  completedAt: string
}

export interface FeatureImportance {
  feature: string
  impact: number
}

export interface MLPrediction {
  id: string
  modelName: string
  modelVersion: string
  portfolioId: string
  volatilityForecastPct: number
  drawdownProbabilityPct: number
  marketRegime: 'Calm' | 'Transition' | 'Stress'
  regimeTimeline: ('Calm' | 'Transition' | 'Stress')[]
  portfolioHealth: number
  confidencePct: number
  featureImportance: FeatureImportance[]
  score: number
  level: RiskLevel
  completedAt: string
}

export interface ExplanationSection {
  title: string
  body: string[]
}

export interface RiskDriver {
  label: string
  pct: number
}

// A risk module is one of the three independent lenses a user can run.
// Any subset may be run, so every downstream view is derived from the set
// that actually completed rather than assuming all three are present.
export type RiskModuleKey = 'stress' | 'tda' | 'ml'

export type RiskModuleStatus = 'idle' | 'running' | 'complete'

export interface RiskModuleMetric {
  label: string
  value: string
  tone?: 'negative' | 'neutral'
}

export interface RiskModuleDefinition {
  key: RiskModuleKey
  title: string
  short: string
  question: string
  route: string
  /** Relative share of the composite score, renormalized over the modules that ran. */
  weight: number
  score: number
  level: RiskLevel
  completedAt: string
  metrics: RiskModuleMetric[]
  driverLabel: string
  explanation: string[]
}

export interface CompositeBreakdownRow {
  key: RiskModuleKey
  title: string
  short: string
  score: number
  level: RiskLevel
  weightPct: number
  contributionPct: number
}

export interface CompositeRisk {
  id: string
  portfolioId: string
  modules: RiskModuleKey[]
  breakdown: CompositeBreakdownRow[]
  compositeScore: number
  level: RiskLevel
  coverageNote: string
  interpretation: string[]
  drivers: RiskDriver[]
  completedAt: string
}

export interface Alert {
  id: string
  title: string
  message: string
  detail: string
  severity: RiskLevel
  source: 'Stress Testing' | 'TDA Analysis' | 'ML Prediction' | 'Composite Risk' | 'System'
  portfolioId?: string
  status: 'Active' | 'Investigating' | 'Dismissed'
  createdAt: string
  /** Set when the alert was raised by a specific risk lens. */
  moduleKey?: RiskModuleKey
  /** Page that answers "why was this raised". */
  investigateRoute?: string
}

export interface AuditEvent {
  id: string
  timestamp: string
  user: string
  service: string
  action: string
  severity: 'Info' | 'Warning' | 'Critical'
  detail: string
}

export interface SystemEvent {
  id: string
  type: string
  timestamp: string
  detail: string
}

export interface ReportDef {
  id: string
  name: string
  description: string
  category: 'Portfolio' | 'Simulation' | 'Stress' | 'TDA' | 'ML' | 'Composite'
}

export interface MLModelDef {
  id: string
  name: string
  version: string
  task: string
  status: 'Production' | 'Staging' | 'Archived'
  accuracy: number
  lastTrained: string
}

export interface UserAccount {
  id: string
  name: string
  email: string
  role: Role
  status: 'Active' | 'Invited' | 'Disabled'
  lastActive: string
}
