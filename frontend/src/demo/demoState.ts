// Frontend state: the signed-in session and the state machine driving the main QuantSim
// POC flow. No backend calls happen here — every transition just flips local state
// and, where the spec calls for it, resolves to deterministic mock results
// after a short simulated processing delay.

import { create } from 'zustand'
import type { SignedInUser } from '../services/api/platform'
import type { RiskModuleKey, RiskModuleStatus, Role } from '../types'
import { ROLE_RANK } from './permissions'

export const FLOW_STEPS = [
  'IDLE',
  'MARKET_SELECTED',
  'SIMULATION_CONFIGURED',
  'SIMULATION_RUNNING',
  'SIMULATION_COMPLETE',
  'PORTFOLIO_CREATED',
  'TRADING_RUNNING',
  'TRADING_COMPLETE',
  'RISK_ANALYSIS_READY',
  'STRESS_COMPLETE',
  'TDA_COMPLETE',
  'ML_COMPLETE',
  'EXPLANATION_READY',
  'COMPOSITE_RISK_READY',
  'ALERT_TRIGGERED',
] as const

export type FlowStep = (typeof FLOW_STEPS)[number]

export const DEMO_STAGES = [
  { key: 'market', label: 'Market', step: 'MARKET_SELECTED' as FlowStep, path: '/market/environments/new' },
  { key: 'simulation', label: 'Simulation', step: 'SIMULATION_COMPLETE' as FlowStep, path: '/simulation/run/1042' },
  { key: 'trading', label: 'Trading', step: 'TRADING_COMPLETE' as FlowStep, path: '/trading/replay/1042' },
  { key: 'stress', label: 'Stress', step: 'STRESS_COMPLETE' as FlowStep, path: '/risk/stress-testing' },
  { key: 'tda', label: 'TDA', step: 'TDA_COMPLETE' as FlowStep, path: '/risk/tda-analysis' },
  { key: 'ml', label: 'ML', step: 'ML_COMPLETE' as FlowStep, path: '/ml/predictions' },
  { key: 'explainability', label: 'Explainability', step: 'EXPLANATION_READY' as FlowStep, path: '/risk/explanations' },
  { key: 'risk', label: 'Risk', step: 'ALERT_TRIGGERED' as FlowStep, path: '/risk/overview' },
] as const

function stepIndex(step: FlowStep) {
  return FLOW_STEPS.indexOf(step)
}

// Risk modules are tracked independently of the linear flow above: a user may
// run one, two, or all three of them in any order, and every risk view derives
// from the set that actually completed.
export type RiskModuleState = Record<RiskModuleKey, RiskModuleStatus>

const IDLE_RISK_MODULES: RiskModuleState = { stress: 'idle', tda: 'idle', ml: 'idle' }

const MODULE_STEP: Record<RiskModuleKey, FlowStep> = {
  stress: 'STRESS_COMPLETE',
  tda: 'TDA_COMPLETE',
  ml: 'ML_COMPLETE',
}

interface DemoState {
  /** True only while a real platform session is held; there is no demo session. */
  authenticated: boolean
  /** The role shown and previewed: the account's own role or a lower one. */
  role: Role
  /** The signed-in account; its role is what the backend enforces. */
  account: SignedInUser | null
  flowStep: FlowStep
  runningFullDemo: boolean
  systemActivityOpen: boolean
  riskModules: RiskModuleState
  riskQueue: RiskModuleKey[]
  /** Modules whose alerts have been raised into the notification tray. */
  alertModules: RiskModuleKey[]
  dismissedAlertIds: string[]
  startSession: (account: SignedInUser) => void
  logout: () => void
  setRole: (role: Role) => void
  advanceTo: (step: FlowStep) => void
  hasReached: (step: FlowStep) => boolean
  resetDemo: () => void
  raiseRiskAlerts: (keys: RiskModuleKey[]) => void
  dismissAlert: (id: string) => void
  setRunningFullDemo: (v: boolean) => void
  toggleSystemActivity: () => void
  queueRiskModules: (keys: RiskModuleKey[]) => void
  startRiskModule: (key: RiskModuleKey) => void
  completeRiskModule: (key: RiskModuleKey) => void
  resetRiskAnalysis: () => void
}

export const useDemoStore = create<DemoState>((set, get) => ({
  authenticated: false,
  role: 'Viewer',
  account: null,
  flowStep: 'IDLE',
  runningFullDemo: false,
  systemActivityOpen: false,
  riskModules: IDLE_RISK_MODULES,
  riskQueue: [],
  alertModules: [],
  dismissedAlertIds: [],
  startSession: (account) => set({ authenticated: true, account, role: account.role }),
  logout: () => set({ authenticated: false, account: null, role: 'Viewer' }),
  // The top bar may preview the account's own role or a lower one, never a higher one
  setRole: (role) =>
    set((s) => (!s.account || ROLE_RANK[role] > ROLE_RANK[s.account.role] ? s : { ...s, role })),
  // Progress only ever moves forward. Revisiting an earlier page must not rewind
  // the flow and wipe out work the user already completed.
  advanceTo: (step) =>
    set((s) => {
      if (stepIndex(step) <= stepIndex(s.flowStep)) return s
      return { ...s, flowStep: step }
    }),
  hasReached: (step) => stepIndex(get().flowStep) >= stepIndex(step),
  resetDemo: () =>
    set({
      flowStep: 'IDLE',
      runningFullDemo: false,
      riskModules: IDLE_RISK_MODULES,
      riskQueue: [],
      alertModules: [],
      dismissedAlertIds: [],
    }),
  raiseRiskAlerts: (keys) => set({ alertModules: keys }),
  dismissAlert: (id) =>
    set((s) => (s.dismissedAlertIds.includes(id) ? s : { ...s, dismissedAlertIds: [...s.dismissedAlertIds, id] })),
  setRunningFullDemo: (v) => set({ runningFullDemo: v }),
  toggleSystemActivity: () => set((s) => ({ systemActivityOpen: !s.systemActivityOpen })),
  queueRiskModules: (keys) => set((s) => ({ riskQueue: keys.filter((k) => s.riskModules[k] !== 'complete') })),
  startRiskModule: (key) =>
    set((s) =>
      s.riskModules[key] === 'complete'
        ? s
        : { ...s, riskModules: { ...s.riskModules, [key]: 'running' } },
    ),
  completeRiskModule: (key) =>
    set((s) => {
      const flowStep = stepIndex(MODULE_STEP[key]) > stepIndex(s.flowStep) ? MODULE_STEP[key] : s.flowStep
      return {
        ...s,
        flowStep,
        riskModules: { ...s.riskModules, [key]: 'complete' },
        riskQueue: s.riskQueue.filter((k) => k !== key),
      }
    }),
  resetRiskAnalysis: () =>
    set({
      riskModules: IDLE_RISK_MODULES,
      riskQueue: [],
      flowStep: 'TRADING_COMPLETE',
      alertModules: [],
      dismissedAlertIds: [],
    }),
}))
