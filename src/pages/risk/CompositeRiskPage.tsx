import { ArrowRight } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import RiskRadar from '../../components/charts/RiskRadar'
import Button from '../../components/forms/Button'
import Panel from '../../components/layout/Panel'
import PageHeader from '../../components/layout/PageHeader'
import RiskBadge from '../../components/status/RiskBadge'
import { useDemoStore } from '../../demo/demoState'
import { COMPOSITE_RISK } from '../../services/mock/data'

export default function CompositeRiskPage() {
  const navigate = useNavigate()
  const advanceTo = useDemoStore((s) => s.advanceTo)

  return (
    <div className="qs-fade-in flex flex-col gap-6">
      <PageHeader
        title="QuantSim Composite Risk"
        breadcrumbs={[{ label: 'Risk', to: '/risk/overview' }, { label: 'Composite' }]}
      />

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-[1fr_1.2fr]">
        <Panel>
          <div className="flex flex-col items-center gap-2 py-6">
            <span className="mono text-6xl font-bold text-[var(--color-text-primary)]">{COMPOSITE_RISK.compositeScore}</span>
            <span className="text-sm text-[var(--color-text-muted)]">/ 100</span>
            <RiskBadge level={COMPOSITE_RISK.level} size="lg" />
          </div>
          <div className="border-t border-[var(--color-border)] pt-4">
            <dl className="flex flex-col gap-2 text-sm">
              <Row label="Stress Testing" value={COMPOSITE_RISK.stressScore} />
              <Row label="TDA" value={COMPOSITE_RISK.tdaScore} />
              <Row label="ML Prediction" value={COMPOSITE_RISK.mlScore} />
              <div className="my-1 h-px bg-[var(--color-border)]" />
              <Row label="Composite" value={COMPOSITE_RISK.compositeScore} bold />
            </dl>
          </div>
        </Panel>

        <Panel title="Risk Contribution">
          <div className="flex justify-center">
            <RiskRadar
              data={[
                { label: 'Stress', value: COMPOSITE_RISK.stressScore },
                { label: 'TDA', value: COMPOSITE_RISK.tdaScore },
                { label: 'ML', value: COMPOSITE_RISK.mlScore },
              ]}
            />
          </div>
        </Panel>
      </div>

      <Panel title="Risk Interpretation">
        <div className="flex flex-col gap-2.5">
          {COMPOSITE_RISK.interpretation.map((p) => (
            <p key={p} className="text-sm leading-relaxed text-[var(--color-text-secondary)]">
              {p}
            </p>
          ))}
        </div>
        <p className="mt-4 border-t border-[var(--color-border)] pt-3 text-xs italic text-[var(--color-text-muted)]">
          This interpretation describes model output only and does not constitute investment advice.
        </p>
      </Panel>

      <div className="flex justify-end">
        <Button
          icon={ArrowRight}
          onClick={() => {
            advanceTo('ALERT_TRIGGERED')
            navigate('/alerts')
          }}
        >
          View Risk Alert
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
