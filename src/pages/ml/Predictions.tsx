import { ArrowRight } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import ContributionBars from '../../components/charts/ContributionBars'
import RegimeTimeline from '../../components/charts/RegimeTimeline'
import Button from '../../components/forms/Button'
import Panel from '../../components/layout/Panel'
import PageHeader from '../../components/layout/PageHeader'
import RiskBadge from '../../components/status/RiskBadge'
import { useDemoStore } from '../../demo/demoState'
import { ML_PREDICTION } from '../../services/mock/data'

export default function Predictions() {
  const navigate = useNavigate()
  const advanceTo = useDemoStore((s) => s.advanceTo)

  return (
    <div className="qs-fade-in flex flex-col gap-6">
      <PageHeader
        title="Machine Learning Intelligence"
        description={`${ML_PREDICTION.modelName} ${ML_PREDICTION.modelVersion}`}
        breadcrumbs={[{ label: 'Risk', to: '/risk/overview' }, { label: 'ML Prediction' }]}
        action={<RiskBadge level={ML_PREDICTION.level} />}
      />

      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <Stat label="Volatility Forecast" value={`${ML_PREDICTION.volatilityForecastPct}%`} />
        <Stat label="Drawdown Probability" value={`${ML_PREDICTION.drawdownProbabilityPct}%`} tone="negative" />
        <Stat label="Market Regime" value={ML_PREDICTION.marketRegime} tone="negative" />
        <Stat label="Portfolio Health" value={`${ML_PREDICTION.portfolioHealth} / 100`} />
      </div>

      <Panel title="Regime Timeline">
        <RegimeTimeline regimes={ML_PREDICTION.regimeTimeline} />
      </Panel>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        <Panel title="Prediction Confidence">
          <div className="flex items-center gap-4">
            <div className="mono text-3xl font-semibold text-[var(--color-text-primary)]">{ML_PREDICTION.confidencePct}%</div>
            <div className="h-2 flex-1 overflow-hidden rounded bg-[var(--color-bg-3)]">
              <div className="h-full rounded bg-[var(--color-accent)]" style={{ width: `${ML_PREDICTION.confidencePct}%` }} />
            </div>
          </div>
        </Panel>
        <Panel title="Feature Importance">
          <ContributionBars
            data={ML_PREDICTION.featureImportance.map((f) => ({ label: f.feature, value: f.impact }))}
            suffix=""
          />
        </Panel>
      </div>

      <div className="flex justify-end">
        <Button
          icon={ArrowRight}
          onClick={() => {
            advanceTo('ML_COMPLETE')
            navigate('/risk/explanations')
          }}
        >
          Explain Prediction
        </Button>
      </div>
    </div>
  )
}

function Stat({ label, value, tone }: { label: string; value: string; tone?: 'negative' }) {
  return (
    <div className="qs-panel rounded p-4">
      <div className="text-xs font-medium uppercase tracking-wide text-[var(--color-text-muted)]">{label}</div>
      <div className={`mono mt-1.5 text-xl font-semibold ${tone === 'negative' ? 'text-[var(--color-risk-elevated)]' : 'text-[var(--color-text-primary)]'}`}>
        {value}
      </div>
    </div>
  )
}
