// Frontend-only state machine driving the main QuantSim POC flow.
// No backend calls happen here — every transition just flips local state
// and, where the spec calls for it, resolves to deterministic mock results
// after a short simulated processing delay.

import { create } from 'zustand'
import type { Role } from '../types'

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

interface DemoState {
  authenticated: boolean
  role: Role
  flowStep: FlowStep
  runningFullDemo: boolean
  alertActive: boolean
  systemActivityOpen: boolean
  login: (role: Role) => void
  logout: () => void
  setRole: (role: Role) => void
  advanceTo: (step: FlowStep) => void
  hasReached: (step: FlowStep) => boolean
  resetDemo: () => void
  dismissAlert: () => void
  setRunningFullDemo: (v: boolean) => void
  toggleSystemActivity: () => void
}

export const useDemoStore = create<DemoState>((set, get) => ({
  authenticated: false,
  role: 'Quant',
  flowStep: 'IDLE',
  runningFullDemo: false,
  alertActive: false,
  systemActivityOpen: false,
  login: (role) => set({ authenticated: true, role }),
  logout: () => set({ authenticated: false }),
  setRole: (role) => set({ role }),
  advanceTo: (step) =>
    set((s) => {
      if (stepIndex(step) <= stepIndex(s.flowStep)) return { flowStep: step }
      return { flowStep: step, alertActive: step === 'ALERT_TRIGGERED' ? true : s.alertActive }
    }),
  hasReached: (step) => stepIndex(get().flowStep) >= stepIndex(step),
  resetDemo: () => set({ flowStep: 'IDLE', runningFullDemo: false, alertActive: false }),
  dismissAlert: () => set({ alertActive: false }),
  setRunningFullDemo: (v) => set({ runningFullDemo: v }),
  toggleSystemActivity: () => set((s) => ({ systemActivityOpen: !s.systemActivityOpen })),
}))
