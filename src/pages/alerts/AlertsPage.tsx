import { AlertTriangle, Eye, Search, X } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import Button from '../../components/forms/Button'
import Panel from '../../components/layout/Panel'
import PageHeader from '../../components/layout/PageHeader'
import RiskBadge from '../../components/status/RiskBadge'
import StatusPill from '../../components/status/StatusPill'
import { useDemoStore } from '../../demo/demoState'
import { useNotifications } from '../../demo/notifications'
import { ALERT } from '../../services/mock/data'

export default function AlertsPage() {
  const navigate = useNavigate()
  const alertActive = useDemoStore((s) => s.alertActive)
  const dismissAlert = useDemoStore((s) => s.dismissAlert)
  const push = useNotifications((s) => s.push)

  return (
    <div className="qs-fade-in flex flex-col gap-6">
      <PageHeader title="Alerts" description="Risk alerts generated across stress testing, TDA and ML analysis." />

      {alertActive ? (
        <div className="qs-panel overflow-hidden rounded border-l-4 border-l-[var(--color-risk-high)]">
          <div className="flex items-start gap-4 p-5">
            <AlertTriangle size={22} className="mt-0.5 shrink-0 text-[var(--color-risk-high)]" />
            <div className="flex-1">
              <div className="flex items-center gap-2">
                <span className="text-sm font-bold uppercase tracking-wide text-[var(--color-risk-high)]">{ALERT.title}</span>
                <RiskBadge level={ALERT.severity} size="sm" />
              </div>
              <div className="mt-1 text-base font-semibold text-[var(--color-text-primary)]">{ALERT.message}</div>
              <div className="mono mt-1 text-sm text-[var(--color-text-secondary)]">{ALERT.detail}</div>
              <div className="mt-3 flex flex-wrap gap-x-6 gap-y-1 text-xs text-[var(--color-text-muted)]">
                <span>Portfolio: <span className="text-[var(--color-text-secondary)]">Momentum Strategy</span></span>
                <span>Source: <span className="text-[var(--color-text-secondary)]">{ALERT.source}</span></span>
                <span>Created: <span className="mono text-[var(--color-text-secondary)]">{ALERT.createdAt}</span></span>
              </div>
              <div className="mt-4 flex gap-2">
                <Button size="sm" icon={Search} onClick={() => navigate('/risk/tda-analysis')}>
                  Investigate
                </Button>
                <Button size="sm" variant="secondary" icon={Eye} onClick={() => navigate('/risk/composite')}>
                  View Analysis
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  icon={X}
                  onClick={() => {
                    dismissAlert()
                    push('Alert dismissed', 'info')
                  }}
                >
                  Dismiss
                </Button>
              </div>
            </div>
          </div>
        </div>
      ) : (
        <Panel>
          <div className="flex items-center gap-2 py-4 text-sm text-[var(--color-text-muted)]">
            <Search size={14} />
            No active alerts. Run the full risk analysis to generate one.
          </div>
        </Panel>
      )}

      <Panel title="Alert History" bodyClassName="p-0">
        <div className="divide-y divide-[var(--color-border)]">
          {[
            { title: ALERT.message, severity: ALERT.severity, time: ALERT.createdAt, status: alertActive ? 'Active' : 'Dismissed' },
            { title: 'Volatility spike detected in NVDA position', severity: 'ELEVATED' as const, time: 'Yesterday 11:02', status: 'Dismissed' },
            { title: 'Calibration for AMZN marked stale', severity: 'MODERATE' as const, time: '2 days ago', status: 'Dismissed' },
          ].map((a, i) => (
            <div key={i} className="flex items-center justify-between gap-4 px-4 py-3">
              <div className="flex items-center gap-3">
                <RiskBadge level={a.severity} size="sm" />
                <span className="text-sm text-[var(--color-text-secondary)]">{a.title}</span>
              </div>
              <div className="flex items-center gap-3">
                <span className="mono text-xs text-[var(--color-text-muted)]">{a.time}</span>
                <StatusPill tone={a.status === 'Active' ? 'danger' : 'neutral'}>{a.status}</StatusPill>
              </div>
            </div>
          ))}
        </div>
      </Panel>
    </div>
  )
}
