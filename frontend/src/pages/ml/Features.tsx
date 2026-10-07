import ContributionBars from '../../components/charts/ContributionBars'
import Panel from '../../components/layout/Panel'
import PageHeader from '../../components/layout/PageHeader'
import { ML_PREDICTION } from '../../services/mock/data'

export default function Features() {
  return (
    <div className="qs-fade-in flex flex-col gap-6">
      <PageHeader title="Features" description="Input features consumed by the Portfolio Risk Model." />
      <Panel title="Current Feature Attribution" subtitle={`${ML_PREDICTION.modelName} ${ML_PREDICTION.modelVersion}`}>
        <ContributionBars data={ML_PREDICTION.featureImportance.map((f) => ({ label: f.feature, value: f.impact }))} suffix="" />
      </Panel>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        {[
          { name: 'Rolling Volatility', description: '20-day realized volatility of portfolio returns.' },
          { name: 'Correlation Change', description: 'Rate of change in pairwise asset correlation.' },
          { name: 'Drawdown', description: 'Current drawdown from portfolio equity peak.' },
          { name: 'Momentum', description: '20-day price momentum across held positions.' },
          { name: 'Volume', description: 'Relative trading volume versus 30-day average.' },
        ].map((f) => (
          <Panel key={f.name} title={f.name}>
            <p className="text-sm text-[var(--color-text-secondary)]">{f.description}</p>
          </Panel>
        ))}
      </div>
    </div>
  )
}
