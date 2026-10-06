import Panel from '../../components/layout/Panel'
import PageHeader from '../../components/layout/PageHeader'
import ExtendedScopeBadge from '../../components/status/ExtendedScopeBadge'

const MODELS = [
  { name: 'GBM', description: 'Geometric Brownian Motion — constant drift and volatility.', usage: '1,204 runs' },
  { name: 'Jump Diffusion', description: 'GBM with discrete jump events driven by a Poisson process.', usage: '318 runs', extended: true },
  { name: 'Ornstein-Uhlenbeck', description: 'Mean-reverting stochastic process for range-bound assets.', usage: '96 runs' },
  { name: 'Regime Switching', description: 'Markov-modulated volatility across market regimes.', usage: '142 runs' },
]

export default function Models() {
  return (
    <div className="qs-fade-in flex flex-col gap-6">
      <PageHeader title="Models" description="Stochastic models available for Monte Carlo simulation." />
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        {MODELS.map((m) => (
          <Panel
            key={m.name}
            title={
              <span className="flex items-center gap-2">
                {m.name}
                {m.extended && <ExtendedScopeBadge compact />}
              </span>
            }
            subtitle={m.usage}
          >
            <p className="text-sm text-[var(--color-text-secondary)]">{m.description}</p>
          </Panel>
        ))}
      </div>
    </div>
  )
}
