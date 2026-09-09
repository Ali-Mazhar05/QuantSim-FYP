import { ArrowRight, ShieldHalf } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import ContributionBars from '../../components/charts/ContributionBars'
import Button from '../../components/forms/Button'
import Panel from '../../components/layout/Panel'
import PageHeader from '../../components/layout/PageHeader'
import EmptyState from '../../components/status/EmptyState'
import { useRiskAnalysis } from '../../demo/useRiskAnalysis'
import { STRESS_RESULT } from '../../services/mock/data'

export default function Attribution() {
  const navigate = useNavigate()
  const { status, composite } = useRiskAnalysis()

  return (
    <div className="qs-fade-in flex flex-col gap-6">
      <PageHeader
        title="Attribution"
        description={
          composite
            ? `Position and signal-level attribution behind the risk score. ${composite.coverageNote}`
            : 'Position and signal-level attribution behind the risk score.'
        }
      />
      {!composite ? (
        <EmptyState
          icon={ShieldHalf}
          title="Nothing to attribute yet"
          description="Attribution is derived from the risk lenses you run."
          action={
            <Button size="sm" icon={ArrowRight} onClick={() => navigate('/risk/overview')}>
              Go to Risk Analysis
            </Button>
          }
        />
      ) : (
        <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
          <Panel title="Risk Drivers" subtitle={composite.coverageNote}>
            <ContributionBars data={composite.drivers.map((d) => ({ label: d.label, value: d.pct }))} />
          </Panel>
          {status.stress === 'complete' && (
            <Panel title="Loss Contribution by Position" subtitle="Correlated Failure scenario">
              <ContributionBars
                data={STRESS_RESULT.contribution.map((c) => ({ label: c.symbol, value: c.pct }))}
                color="var(--color-risk-high)"
              />
            </Panel>
          )}
        </div>
      )}
    </div>
  )
}
