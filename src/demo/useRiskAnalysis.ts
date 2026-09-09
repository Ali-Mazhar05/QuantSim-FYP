// Single source of truth for "which risk lenses did the user actually run".
// Every risk view reads from here so a one-, two-, or three-module run renders
// consistently without any page assuming the full set is present.

import { useMemo } from 'react'
import { buildCompositeRisk } from '../services/mock/compositeRisk'
import { RISK_MODULE_ORDER, RISK_MODULES } from '../services/mock/riskModules'
import type { RiskModuleDefinition, RiskModuleKey } from '../types'
import { useDemoStore } from './demoState'

export interface RiskAnalysisView {
  status: Record<RiskModuleKey, 'idle' | 'running' | 'complete'>
  completed: RiskModuleKey[]
  completedModules: RiskModuleDefinition[]
  pending: RiskModuleKey[]
  nextPending: RiskModuleKey | null
  composite: ReturnType<typeof buildCompositeRisk>
  hasAnyResult: boolean
}

export function useRiskAnalysis(): RiskAnalysisView {
  const status = useDemoStore((s) => s.riskModules)
  const queue = useDemoStore((s) => s.riskQueue)

  return useMemo(() => {
    const completed = RISK_MODULE_ORDER.filter((k) => status[k] === 'complete')
    const pending = queue.filter((k) => status[k] !== 'complete')
    return {
      status,
      completed,
      completedModules: completed.map((k) => RISK_MODULES[k]),
      pending,
      nextPending: pending[0] ?? null,
      composite: buildCompositeRisk(completed),
      hasAnyResult: completed.length > 0,
    }
  }, [status, queue])
}
