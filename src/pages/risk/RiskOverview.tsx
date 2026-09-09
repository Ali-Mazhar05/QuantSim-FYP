import clsx from 'clsx'
import { ArrowRight, Check, Network as NetworkIcon, RotateCcw, ShieldAlert, Sparkles } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import ContributionBars from '../../components/charts/ContributionBars'
import Button from '../../components/forms/Button'
import Panel from '../../components/layout/Panel'
import PageHeader from '../../components/layout/PageHeader'
import KpiCard from '../../components/status/KpiCard'
import RiskBadge from '../../components/status/RiskBadge'
import StatusPill from '../../components/status/StatusPill'
import { useDemoStore } from '../../demo/demoState'
import { useRiskAnalysis } from '../../demo/useRiskAnalysis'
import { PORTFOLIO } from '../../services/mock/data'
import { RISK_MODULES, RISK_MODULE_ORDER } from '../../services/mock/riskModules'
import type { RiskModuleKey } from '../../types'

const MODULE_ICONS: Record<RiskModuleKey, LucideIcon> = {
  stress: ShieldAlert,
  tda: NetworkIcon,
  ml: Sparkles,
}

export default function RiskOverview() {
  const navigate = useNavigate()
  const queueRiskModules = useDemoStore((s) => s.queueRiskModules)
  const resetRiskAnalysis = useDemoStore((s) => s.resetRiskAnalysis)
  const { status, completed, completedModules, nextPending, composite } = useRiskAnalysis()

  const [picked, setPicked] = useState<RiskModuleKey[]>(RISK_MODULE_ORDER)
  const selected = useMemo(() => picked.filter((k) => status[k] !== 'complete'), [picked, status])
  const remaining = RISK_MODULE_ORDER.filter((k) => status[k] !== 'complete')

  const toggle = (key: RiskModuleKey) =>
    setPicked((p) => (p.includes(key) ? p.filter((k) => k !== key) : [...p, key]))

  const run = (keys: RiskModuleKey[]) => {
    if (keys.length === 0) return
    queueRiskModules(keys)
    navigate(RISK_MODULES[keys[0]].route)
  }

  return (
    <div className="qs-fade-in flex flex-col gap-6">
      <PageHeader
        eyebrow="Step 7 of 8 — Risk"
        title="Risk Analysis"
        description={`${PORTFOLIO.name} · Simulation #1042`}
        action={
          completed.length > 0 && (
            <StatusPill tone="success" dot>
              {completed.length} of 3 lenses run
            </StatusPill>
          )
        }
      />

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <KpiCard label="Portfolio Value" value={`$${PORTFOLIO.currentValue.toLocaleString()}`} />
        <KpiCard label="Return" value={`+${PORTFOLIO.returnPct}%`} deltaTone="positive" />
        <KpiCard label="Volatility" value={`${PORTFOLIO.volatilityPct}%`} />
        <KpiCard label="Max Drawdown" value={`${PORTFOLIO.maxDrawdownPct}%`} deltaTone="negative" />
      </div>

      {nextPending && (
        <Panel
          title="Pipeline in progress"
          subtitle={`Next up: ${RISK_MODULES[nextPending].title}`}
          action={
            <Button size="sm" icon={ArrowRight} onClick={() => navigate(RISK_MODULES[nextPending].route)}>
              Continue
            </Button>
          }
        >
          <p className="text-sm text-[var(--color-text-secondary)]">
            You selected more than one risk lens. Each one returns here when it finishes, so you can stop at any
            point and analyse only what you have run.
          </p>
        </Panel>
      )}

      <Panel
        title="Risk Modules"
        subtitle="Run one, two, or all three. The composite score is computed from whichever lenses you run."
      >
        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          {RISK_MODULE_ORDER.map((key) => {
            const mod = RISK_MODULES[key]
            const Icon = MODULE_ICONS[key]
            const state = status[key]
            const isSelected = selected.includes(key)
            return (
              <div
                key={key}
                className={clsx(
                  'flex flex-col gap-3 rounded border p-4 transition-colors',
                  state === 'complete'
                    ? 'border-[var(--color-border-strong)]'
                    : isSelected
                      ? 'border-[var(--color-accent-strong)] bg-[var(--color-accent)]/8'
                      : 'border-[var(--color-border-strong)]',
                )}
              >
                <div className="flex items-start justify-between gap-2">
                  <Icon size={18} className="text-[var(--color-accent-strong)]" />
                  {state === 'complete' ? (
                    <RiskBadge level={mod.level} size="sm" />
                  ) : state === 'running' ? (
                    <StatusPill tone="info">Running</StatusPill>
                  ) : (
                    <StatusPill>Not run</StatusPill>
                  )}
                </div>

                <div>
                  <div className="text-sm font-semibold text-[var(--color-text-primary)]">{mod.title}</div>
                  <div className="mt-1 text-xs text-[var(--color-text-muted)]">"{mod.question}"</div>
                </div>

                {state === 'complete' ? (
                  <>
                    <div className="flex items-baseline gap-1.5">
                      <span className="mono text-2xl font-semibold text-[var(--color-text-primary)]">{mod.score}</span>
                      <span className="text-xs text-[var(--color-text-muted)]">/ 100</span>
                    </div>
                    <dl className="flex flex-col gap-1.5 border-t border-[var(--color-border)] pt-3 text-xs">
                      {mod.metrics.map((m) => (
                        <div key={m.label} className="flex items-center justify-between gap-2">
                          <dt className="text-[var(--color-text-muted)]">{m.label}</dt>
                          <dd
                            className={clsx(
                              'mono font-medium',
                              m.tone === 'negative'
                                ? 'text-[var(--color-risk-elevated)]'
                                : 'text-[var(--color-text-primary)]',
                            )}
                          >
                            {m.value}
                          </dd>
                        </div>
                      ))}
                    </dl>
                    <Button
                      size="sm"
                      variant="secondary"
                      icon={ArrowRight}
                      className="mt-auto"
                      onClick={() => navigate(mod.route)}
                    >
                      View results
                    </Button>
                  </>
                ) : (
                  <>
                    <button
                      onClick={() => toggle(key)}
                      className="flex items-center gap-2 text-left text-xs font-medium text-[var(--color-text-secondary)]"
                    >
                      <span
                        className={clsx(
                          'flex h-4 w-4 items-center justify-center rounded border',
                          isSelected
                            ? 'border-[var(--color-accent-strong)] bg-[var(--color-accent)] text-black'
                            : 'border-[var(--color-border-control)]',
                        )}
                      >
                        {isSelected && <Check size={11} strokeWidth={3} />}
                      </span>
                      Include in this run
                    </button>
                    <Button
                      size="sm"
                      variant="secondary"
                      icon={ArrowRight}
                      className="mt-auto"
                      onClick={() => run([key])}
                    >
                      Run this lens only
                    </Button>
                  </>
                )}
              </div>
            )
          })}
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-3 border-t border-[var(--color-border)] pt-4">
          <Button icon={ArrowRight} disabled={selected.length === 0} onClick={() => run(selected)}>
            Run selected ({selected.length})
          </Button>
          {remaining.length > 1 && (
            <Button variant="secondary" onClick={() => run(remaining)}>
              Run all remaining
            </Button>
          )}
          {completed.length > 0 && (
            <Button
              variant="ghost"
              icon={RotateCcw}
              onClick={() => {
                resetRiskAnalysis()
                setPicked(RISK_MODULE_ORDER)
              }}
            >
              Reset risk analysis
            </Button>
          )}
        </div>
      </Panel>

      {completed.length >= 2 && composite && (
        <Panel title="Module Comparison" subtitle={composite.coverageNote}>
          <ContributionBars data={completedModules.map((m) => ({ label: m.short, value: m.score }))} suffix="" />
          <div className="mt-4 overflow-x-auto">
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
              </tbody>
            </table>
          </div>
        </Panel>
      )}

      <div className="flex flex-wrap items-center justify-end gap-3">
        {completed.length === 0 && (
          <span className="text-xs text-[var(--color-text-muted)]">
            Run at least one risk lens to continue to the explanation.
          </span>
        )}
        <Button
          icon={ArrowRight}
          disabled={completed.length === 0}
          onClick={() => navigate('/risk/explanations')}
        >
          Continue to Explanation
        </Button>
      </div>
    </div>
  )
}
