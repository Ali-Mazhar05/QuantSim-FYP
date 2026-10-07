// Alerts are derived from the lenses whose results were raised into the tray,
// minus anything the user dismissed. Nothing is stored twice.

import { useMemo } from 'react'
import { buildCompositeRisk } from '../services/mock/compositeRisk'
import { buildRiskAlerts } from '../services/mock/alerts'
import type { Alert } from '../types'
import { useDemoStore } from './demoState'

export interface RiskAlertsView {
  alerts: Alert[]
  active: Alert[]
  dismissed: Alert[]
  activeCount: number
}

export function useRiskAlerts(): RiskAlertsView {
  const alertModules = useDemoStore((s) => s.alertModules)
  const dismissedAlertIds = useDemoStore((s) => s.dismissedAlertIds)

  return useMemo(() => {
    const alerts = buildRiskAlerts(buildCompositeRisk(alertModules)).map((a) =>
      dismissedAlertIds.includes(a.id) ? { ...a, status: 'Dismissed' as const } : a,
    )
    const active = alerts.filter((a) => a.status === 'Active')
    return {
      alerts,
      active,
      dismissed: alerts.filter((a) => a.status === 'Dismissed'),
      activeCount: active.length,
    }
  }, [alertModules, dismissedAlertIds])
}
