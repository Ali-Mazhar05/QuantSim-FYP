import Panel from '../../components/layout/Panel'
import PageHeader from '../../components/layout/PageHeader'
import ErrorNote from '../../components/status/ErrorNote'
import ExtendedScopeBadge from '../../components/status/ExtendedScopeBadge'
import { useRuns } from '../../hooks/useSimulation'
import type { ModelName } from '../../services/api/simulation'

// Jump diffusion is a core model (B10, B15, B16). Regime switching has no generator or fit in this
// iteration: it stays visible as an Extended item, as ADR 06 says, and is not offered for a run.
const MODELS: { name: string; model: ModelName | null; description: string; extended?: boolean }[] = [
  { name: 'GBM', model: 'gbm', description: 'Geometric Brownian Motion — constant drift and volatility.' },
  { name: 'Jump Diffusion', model: 'merton', description: 'GBM with discrete jump events driven by a Poisson process.' },
  { name: 'Ornstein-Uhlenbeck', model: 'ou', description: 'Mean-reverting stochastic process for range-bound assets.' },
  { name: 'Regime Switching', model: null, description: 'Markov-modulated volatility across market regimes.', extended: true },
]

export default function Models() {
  const { runs, error } = useRuns()
  const usage = (model: ModelName | null): string => {
    if (model === null) return 'Extended scope: not available yet'
    if (runs === null) return 'Counting runs…'
    const n = runs.filter((r) => r.model === model).length
    return `${n.toLocaleString()} ${n === 1 ? 'run' : 'runs'}`
  }

  return (
    <div className="qs-fade-in flex flex-col gap-6" data-testid="page-models">
      <PageHeader title="Models" description="Stochastic models available for Monte Carlo simulation." />
      {error && <ErrorNote error={error} />}
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
            subtitle={<span data-testid={`usage-${m.model ?? 'extended'}`}>{usage(m.model)}</span>}
          >
            <p className="text-sm text-[var(--color-text-secondary)]">{m.description}</p>
          </Panel>
        ))}
      </div>
    </div>
  )
}
