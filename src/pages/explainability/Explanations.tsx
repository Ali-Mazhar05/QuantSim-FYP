import { ArrowRight, Network as NetworkIcon, ShieldAlert, Sparkles } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import ContributionBars from '../../components/charts/ContributionBars'
import Button from '../../components/forms/Button'
import Panel from '../../components/layout/Panel'
import PageHeader from '../../components/layout/PageHeader'
import ExtendedScopeBanner from '../../components/status/ExtendedScopeBanner'
import { useDemoStore } from '../../demo/demoState'
import { COMPOSITE_RISK } from '../../services/mock/data'

const SECTIONS = [
  {
    icon: NetworkIcon,
    title: 'TDA Explanation',
    body: [
      'Market structure has become significantly more interconnected over the latest rolling windows.',
      'This reduces diversification and indicates a transition toward a more synchronized market state.',
    ],
  },
  {
    icon: ShieldAlert,
    title: 'Stress Explanation',
    body: [
      'Under the correlated-failure scenario, portfolio losses increase because several large positions become exposed to the same market movement.',
    ],
  },
  {
    icon: Sparkles,
    title: 'ML Explanation',
    body: [
      'The predicted drawdown probability increased primarily because correlation changes and volatility have moved sharply higher.',
    ],
  },
]

export default function Explanations() {
  const navigate = useNavigate()
  const advanceTo = useDemoStore((s) => s.advanceTo)

  return (
    <div className="qs-fade-in flex flex-col gap-6">
      <PageHeader
        title="Why is risk elevated?"
        description="QuantSim explains the composite risk score by tracing it back to each underlying signal."
        breadcrumbs={[{ label: 'Risk', to: '/risk/overview' }, { label: 'Explainability' }]}
      />

      <ExtendedScopeBanner>
        This walkthrough is illustrative narrative text generated from the demo scenario. The production XAI
        service that generates these explanations from live model internals is planned beyond the current build.
      </ExtendedScopeBanner>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        {SECTIONS.map((s) => (
          <Panel key={s.title} title={<span className="flex items-center gap-2"><s.icon size={15} className="text-[var(--color-accent-strong)]" />{s.title}</span>}>
            <div className="flex flex-col gap-2">
              {s.body.map((p) => (
                <p key={p} className="text-sm leading-relaxed text-[var(--color-text-secondary)]">
                  {p}
                </p>
              ))}
            </div>
          </Panel>
        ))}
      </div>

      <Panel title="Primary Risk Drivers">
        <ContributionBars data={COMPOSITE_RISK.drivers.map((d) => ({ label: d.label, value: d.pct }))} />
      </Panel>

      <div className="flex justify-end">
        <Button
          icon={ArrowRight}
          onClick={() => {
            advanceTo('EXPLANATION_READY')
            navigate('/risk/composite')
          }}
        >
          View Composite Risk
        </Button>
      </div>
    </div>
  )
}
