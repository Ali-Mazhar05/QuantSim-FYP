import ContributionBars from '../../components/charts/ContributionBars'
import Panel from '../../components/layout/Panel'
import PageHeader from '../../components/layout/PageHeader'
import { COMPOSITE_RISK, STRESS_RESULT } from '../../services/mock/data'

export default function Attribution() {
  return (
    <div className="qs-fade-in flex flex-col gap-6">
      <PageHeader title="Attribution" description="Position and signal-level attribution behind the composite risk score." />
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        <Panel title="Composite Risk Drivers">
          <ContributionBars data={COMPOSITE_RISK.drivers.map((d) => ({ label: d.label, value: d.pct }))} />
        </Panel>
        <Panel title="Loss Contribution by Position" subtitle="Correlated Failure scenario">
          <ContributionBars data={STRESS_RESULT.contribution.map((c) => ({ label: c.symbol, value: c.pct }))} color="var(--color-risk-high)" />
        </Panel>
      </div>
    </div>
  )
}
