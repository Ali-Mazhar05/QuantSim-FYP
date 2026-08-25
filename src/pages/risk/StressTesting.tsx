import clsx from 'clsx'
import { ArrowRight } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import ContributionBars from '../../components/charts/ContributionBars'
import Button from '../../components/forms/Button'
import Panel from '../../components/layout/Panel'
import PageHeader from '../../components/layout/PageHeader'
import RiskBadge from '../../components/status/RiskBadge'
import StatusPill from '../../components/status/StatusPill'
import { useDemoStore } from '../../demo/demoState'
import { STRESS_RESULT, STRESS_SCENARIOS } from '../../services/mock/data'
import type { StressScenarioId } from '../../types'

const PROCESSING_STEPS = ['Applying scenario…', 'Revaluing portfolio…', 'Calculating losses…', 'Generating recovery profile…']

export default function StressTesting() {
  const navigate = useNavigate()
  const advanceTo = useDemoStore((s) => s.advanceTo)
  const hasReached = useDemoStore((s) => s.hasReached)

  const [scenario, setScenario] = useState<StressScenarioId>('correlated-failure')
  const [phase, setPhase] = useState<'select' | 'processing' | 'complete'>(hasReached('STRESS_COMPLETE') ? 'complete' : 'select')
  const [step, setStep] = useState(0)

  useEffect(() => {
    if (phase !== 'processing') return
    if (step >= PROCESSING_STEPS.length) {
      const t = setTimeout(() => {
        setPhase('complete')
        advanceTo('STRESS_COMPLETE')
      }, 350)
      return () => clearTimeout(t)
    }
    const t = setTimeout(() => setStep((s) => s + 1), 500)
    return () => clearTimeout(t)
  }, [phase, step, advanceTo])

  const selected = STRESS_SCENARIOS.find((s) => s.id === scenario)!

  return (
    <div className="qs-fade-in flex flex-col gap-6">
      <PageHeader
        title="Stress Testing"
        breadcrumbs={[{ label: 'Risk', to: '/risk/overview' }, { label: 'Stress Testing' }]}
        description="Evaluate portfolio resilience under adverse market scenarios."
        action={phase === 'complete' && <StatusPill tone="success" dot>Complete</StatusPill>}
      />

      <Panel title="Scenario">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-5">
          {STRESS_SCENARIOS.map((s) => (
            <button
              key={s.id}
              disabled={phase === 'processing'}
              onClick={() => setScenario(s.id)}
              className={clsx(
                'rounded border p-3.5 text-left transition-colors disabled:opacity-60',
                scenario === s.id ? 'border-[var(--color-accent-strong)] bg-[var(--color-accent)]/8' : 'border-[var(--color-border-strong)] hover:border-[var(--color-border-strong)]/80',
              )}
            >
              <div className={clsx('text-sm font-semibold', scenario === s.id ? 'text-[var(--color-accent-strong)]' : 'text-[var(--color-text-primary)]')}>{s.name}</div>
            </button>
          ))}
        </div>
        <p className="mt-3 text-xs text-[var(--color-text-muted)]">{selected.description}</p>

        {phase === 'select' && (
          <div className="mt-4">
            <Button
              onClick={() => {
                setPhase('processing')
                setStep(0)
              }}
            >
              Run Stress Test
            </Button>
          </div>
        )}
      </Panel>

      {phase === 'processing' && (
        <Panel title="Processing">
          <div className="flex flex-col gap-2.5">
            {PROCESSING_STEPS.map((s, i) => (
              <div key={s} className={clsx('flex items-center gap-2.5 text-sm', i < step ? 'text-[var(--color-text-primary)]' : i === step ? 'text-[var(--color-accent-strong)]' : 'text-[var(--color-text-muted)]')}>
                <span
                  className={clsx(
                    'h-2 w-2 rounded-full',
                    i < step ? 'bg-[var(--color-risk-low)]' : i === step ? 'bg-[var(--color-accent-strong)] qs-live-dot' : 'bg-[var(--color-border-strong)]',
                  )}
                />
                {s}
              </div>
            ))}
          </div>
        </Panel>
      )}

      {phase === 'complete' && (
        <>
          <Panel title="Stress Test Complete" subtitle={`Scenario: ${selected.name}`} action={<RiskBadge level={STRESS_RESULT.level} />}>
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
              <Stat label="Maximum Loss" value={`${STRESS_RESULT.maxLossPct}%`} />
              <Stat label="VaR" value={`${STRESS_RESULT.var}%`} />
              <Stat label="CVaR" value={`${STRESS_RESULT.cvar}%`} />
              <Stat label="Recovery Time" value={`${STRESS_RESULT.recoveryDays} days`} tone="neutral" />
            </div>
          </Panel>

          <Panel title="Contribution to Loss">
            <ContributionBars
              data={STRESS_RESULT.contribution.map((c) => ({ label: c.symbol, value: c.pct }))}
              color="var(--color-risk-high)"
            />
          </Panel>

          <div className="flex justify-end">
            <Button icon={ArrowRight} onClick={() => navigate('/risk/explanations')}>
              View Explanation
            </Button>
          </div>
        </>
      )}
    </div>
  )
}

function Stat({ label, value, tone = 'negative' }: { label: string; value: string; tone?: 'negative' | 'neutral' }) {
  return (
    <div>
      <div className="text-xs text-[var(--color-text-muted)]">{label}</div>
      <div className={clsx('mono mt-0.5 text-lg font-semibold', tone === 'negative' ? 'text-[var(--color-risk-severe)]' : 'text-[var(--color-text-primary)]')}>
        {value}
      </div>
    </div>
  )
}
