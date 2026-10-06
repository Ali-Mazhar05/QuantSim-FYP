import { ArrowRight, Network as NetworkIcon, ShieldAlert, ShieldHalf, Sparkles } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import clsx from 'clsx'
import { useNavigate } from 'react-router-dom'
import ContributionBars from '../../components/charts/ContributionBars'
import Button from '../../components/forms/Button'
import Panel from '../../components/layout/Panel'
import PageHeader from '../../components/layout/PageHeader'
import EmptyState from '../../components/status/EmptyState'
import ExtendedScopeBanner from '../../components/status/ExtendedScopeBanner'
import { useDemoStore } from '../../demo/demoState'
import { useRiskAnalysis } from '../../demo/useRiskAnalysis'
import type { RiskModuleKey } from '../../types'

const MODULE_ICONS: Record<RiskModuleKey, LucideIcon> = {
  stress: ShieldAlert,
  tda: NetworkIcon,
  ml: Sparkles,
}

export default function Explanations() {
  const navigate = useNavigate()
  const advanceTo = useDemoStore((s) => s.advanceTo)
  const { completedModules, composite } = useRiskAnalysis()

  if (!composite) {
    return (
      <div className="qs-fade-in flex flex-col gap-6">
        <PageHeader
          title="Why is risk elevated?"
          description="QuantSim explains the risk score by tracing it back to each underlying signal."
          breadcrumbs={[{ label: 'Risk', to: '/risk/overview' }, { label: 'Explainability' }]}
        />
        <EmptyState
          icon={ShieldHalf}
          title="No risk lens has been run yet"
          description="Run stress testing, TDA, or the ML prediction first. The explanation covers whichever lenses you run."
          action={
            <Button size="sm" icon={ArrowRight} onClick={() => navigate('/risk/overview')}>
              Go to Risk Analysis
            </Button>
          }
        />
      </div>
    )
  }

  return (
    <div className="qs-fade-in flex flex-col gap-6">
      <PageHeader
        title="Why is risk elevated?"
        description={composite.coverageNote}
        breadcrumbs={[{ label: 'Risk', to: '/risk/overview' }, { label: 'Explainability' }]}
      />

      <ExtendedScopeBanner>
        This walkthrough is illustrative narrative text generated from the demo scenario. The production XAI
        service that generates these explanations from live model internals is planned beyond the current build.
      </ExtendedScopeBanner>

      <div
        className={clsx(
          'grid grid-cols-1 gap-4',
          completedModules.length === 2 && 'lg:grid-cols-2',
          completedModules.length === 3 && 'lg:grid-cols-3',
        )}
      >
        {completedModules.map((mod) => {
          const Icon = MODULE_ICONS[mod.key]
          return (
            <Panel
              key={mod.key}
              title={
                <span className="flex items-center gap-2">
                  <Icon size={15} className="text-[var(--color-accent-strong)]" />
                  {mod.title} Explanation
                </span>
              }
            >
              <div className="flex flex-col gap-2">
                {mod.explanation.map((p) => (
                  <p key={p} className="text-sm leading-relaxed text-[var(--color-text-secondary)]">
                    {p}
                  </p>
                ))}
              </div>
            </Panel>
          )
        })}
      </div>

      <Panel title="Primary Risk Drivers" subtitle={composite.coverageNote}>
        <ContributionBars data={composite.drivers.map((d) => ({ label: d.label, value: d.pct }))} />
      </Panel>

      <div className="flex justify-end">
        <Button
          icon={ArrowRight}
          onClick={() => {
            advanceTo('EXPLANATION_READY')
            navigate('/risk/composite')
          }}
        >
          View Risk Hub
        </Button>
      </div>
    </div>
  )
}
