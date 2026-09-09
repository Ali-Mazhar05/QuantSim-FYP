import { ArrowRight, LayoutDashboard, ShieldHalf } from 'lucide-react'
import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import ContributionBars from '../../components/charts/ContributionBars'
import RiskRadar from '../../components/charts/RiskRadar'
import Button from '../../components/forms/Button'
import Panel from '../../components/layout/Panel'
import PageHeader from '../../components/layout/PageHeader'
import EmptyState from '../../components/status/EmptyState'
import RiskBadge from '../../components/status/RiskBadge'
import StatusPill from '../../components/status/StatusPill'
import { useDemoStore } from '../../demo/demoState'
import { useNotifications } from '../../demo/notifications'
import { useRiskAnalysis } from '../../demo/useRiskAnalysis'
import { useRiskAlerts } from '../../demo/useRiskAlerts'
import { RISK_MODULES, RISK_MODULE_ORDER } from '../../services/mock/riskModules'

export default function CompositeRiskPage() {
  const navigate = useNavigate()
  const advanceTo = useDemoStore((s) => s.advanceTo)
  const queueRiskModules = useDemoStore((s) => s.queueRiskModules)
  const raiseRiskAlerts = useDemoStore((s) => s.raiseRiskAlerts)
  const alertModules = useDemoStore((s) => s.alertModules)
  const push = useNotifications((s) => s.push)
  const { status, completed, composite } = useRiskAnalysis()
  const { activeCount } = useRiskAlerts()

  // Reaching the hub is what raises the alerts: the lenses that ran now have a
  // score, so anything above threshold lands in the notification tray.
  const raisedKey = alertModules.join(',')
  const completedKey = completed.join(',')
  useEffect(() => {
    if (completedKey.length === 0 || raisedKey === completedKey) return
    raiseRiskAlerts(completedKey.split(',') as typeof completed)
    push('Risk alerts generated', 'warning')
  }, [completedKey, raisedKey, raiseRiskAlerts, push])

  if (!composite) {
    return (
      <div className="qs-fade-in flex flex-col gap-6">
        <PageHeader
          title="QuantSim Risk Hub"
          breadcrumbs={[{ label: 'Risk', to: '/risk/overview' }, { label: 'Risk Hub' }]}
        />
        <EmptyState
          icon={ShieldHalf}
          title="No composite risk yet"
          description="The composite score is computed from the risk lenses you run. Run at least one to see it here."
          action={
            <Button size="sm" icon={ArrowRight} onClick={() => navigate('/risk/overview')}>
              Go to Risk Analysis
            </Button>
          }
        />
      </div>
    )
  }

  const single = composite.modules.length === 1
  const missing = RISK_MODULE_ORDER.filter((k) => status[k] !== 'complete')

  return (
    <div className="qs-fade-in flex flex-col gap-6">
      <PageHeader
        title="QuantSim Risk Hub"
        description={composite.coverageNote}
        breadcrumbs={[{ label: 'Risk', to: '/risk/overview' }, { label: 'Risk Hub' }]}
        action={
          <StatusPill tone={composite.modules.length === 3 ? 'success' : 'warning'} dot>
            {composite.modules.length} of 3 lenses
          </StatusPill>
        }
      />

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-[1fr_1.2fr]">
        <Panel title={single ? 'Risk Score' : 'Composite Risk Score'}>
          <div className="flex flex-col items-center gap-2 py-6">
            <span className="mono text-6xl font-bold text-[var(--color-text-primary)]">{composite.compositeScore}</span>
            <span className="text-sm text-[var(--color-text-muted)]">/ 100</span>
            <RiskBadge level={composite.level} size="lg" />
          </div>
          <div className="border-t border-[var(--color-border)] pt-4">
            <dl className="flex flex-col gap-2 text-sm">
              {composite.breakdown.map((row) => (
                <Row key={row.key} label={row.title} value={row.score} />
              ))}
              <div className="my-1 h-px bg-[var(--color-border)]" />
              <Row label={single ? 'Score' : 'Composite'} value={composite.compositeScore} bold />
            </dl>
            {!single && (
              <p className="mt-3 text-xs text-[var(--color-text-muted)]">
                Weighted mean of the lenses that ran, renormalized so the weights sum to 100%.
              </p>
            )}
          </div>
        </Panel>

        <Panel title="Risk Comparison" subtitle={single ? 'Only one lens was run' : 'Score by risk lens'}>
          {composite.modules.length === 3 ? (
            <div className="flex justify-center">
              <RiskRadar data={composite.breakdown.map((row) => ({ label: row.short, value: row.score }))} />
            </div>
          ) : (
            <ContributionBars
              data={composite.breakdown.map((row) => ({ label: row.short, value: row.score }))}
              suffix=""
            />
          )}

          <div className="mt-5 overflow-x-auto border-t border-[var(--color-border)] pt-4">
            <table className="w-full text-left text-xs">
              <thead className="text-[var(--color-text-muted)]">
                <tr>
                  <th className="py-1.5 pr-3 font-medium">Lens</th>
                  <th className="py-1.5 pr-3 font-medium">Score</th>
                  <th className="py-1.5 pr-3 font-medium">Level</th>
                  <th className="py-1.5 pr-3 font-medium">Weight</th>
                  <th className="py-1.5 font-medium">Contribution</th>
                </tr>
              </thead>
              <tbody>
                {composite.breakdown.map((row) => (
                  <tr key={row.key} className="border-t border-[var(--color-border)]">
                    <td className="py-2 pr-3 font-medium text-[var(--color-text-primary)]">{row.title}</td>
                    <td className="mono py-2 pr-3 text-[var(--color-text-primary)]">{row.score}</td>
                    <td className="py-2 pr-3">
                      <RiskBadge level={row.level} size="sm" />
                    </td>
                    <td className="mono py-2 pr-3 text-[var(--color-text-secondary)]">{row.weightPct}%</td>
                    <td className="mono py-2 text-[var(--color-text-secondary)]">{row.contributionPct}%</td>
                  </tr>
                ))}
                {missing.map((key) => (
                  <tr key={key} className="border-t border-[var(--color-border)] text-[var(--color-text-muted)]">
                    <td className="py-2 pr-3">{RISK_MODULES[key].title}</td>
                    <td className="py-2 pr-3">—</td>
                    <td className="py-2 pr-3">
                      <StatusPill>Not run</StatusPill>
                    </td>
                    <td className="py-2 pr-3">—</td>
                    <td className="py-2">—</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      </div>

      <Panel title="Risk Drivers" subtitle="Share of the score attributed to each signal">
        <ContributionBars data={composite.drivers.map((d) => ({ label: d.label, value: d.pct }))} />
      </Panel>

      <Panel title="Risk Interpretation">
        <div className="flex flex-col gap-2.5">
          {composite.interpretation.map((p) => (
            <p key={p} className="text-sm leading-relaxed text-[var(--color-text-secondary)]">
              {p}
            </p>
          ))}
        </div>
        <p className="mt-4 border-t border-[var(--color-border)] pt-3 text-xs italic text-[var(--color-text-muted)]">
          This interpretation describes model output only and does not constitute investment advice.
        </p>
      </Panel>

      <div className="flex flex-wrap items-center justify-end gap-3">
        {activeCount > 0 && (
          <span className="text-xs text-[var(--color-text-muted)]">
            {activeCount} {activeCount === 1 ? 'alert' : 'alerts'} raised in your notifications.
          </span>
        )}
        {missing.length > 0 && (
          <Button
            variant="secondary"
            icon={ArrowRight}
            onClick={() => {
              queueRiskModules(missing)
              navigate(RISK_MODULES[missing[0]].route)
            }}
          >
            Run remaining {missing.length === 1 ? 'lens' : 'lenses'}
          </Button>
        )}
        <Button
          icon={LayoutDashboard}
          onClick={() => {
            advanceTo('ALERT_TRIGGERED')
            navigate('/dashboard')
          }}
        >
          Finish: Updated Dashboard
        </Button>
      </div>
    </div>
  )
}

function Row({ label, value, bold }: { label: string; value: number; bold?: boolean }) {
  return (
    <div className="flex items-center justify-between">
      <dt className={bold ? 'font-semibold text-[var(--color-text-primary)]' : 'text-[var(--color-text-secondary)]'}>{label}</dt>
      <dd className={`mono ${bold ? 'text-base font-bold text-[var(--color-text-primary)]' : 'text-[var(--color-text-primary)]'}`}>{value}</dd>
    </div>
  )
}
