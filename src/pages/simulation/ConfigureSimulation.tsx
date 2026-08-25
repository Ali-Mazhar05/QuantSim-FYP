import clsx from 'clsx'
import { ArrowRight } from 'lucide-react'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Button from '../../components/forms/Button'
import Panel from '../../components/layout/Panel'
import PageHeader from '../../components/layout/PageHeader'
import StatusPill from '../../components/status/StatusPill'
import { useDemoStore } from '../../demo/demoState'
import { CALIBRATIONS } from '../../services/mock/data'
import type { StochasticModel } from '../../types'

const MODELS: { id: StochasticModel; description: string }[] = [
  { id: 'GBM', description: 'Geometric Brownian Motion' },
  { id: 'Jump Diffusion', description: 'Diffusion with discrete jump events' },
  { id: 'Ornstein-Uhlenbeck', description: 'Mean-reverting stochastic process' },
  { id: 'Regime Switching', description: 'Markov-modulated volatility regimes' },
]

export default function ConfigureSimulation() {
  const navigate = useNavigate()
  const advanceTo = useDemoStore((s) => s.advanceTo)
  const [model, setModel] = useState<StochasticModel>('GBM')
  const calibration = CALIBRATIONS[0]

  return (
    <div className="qs-fade-in flex flex-col gap-6">
      <PageHeader
        eyebrow="Step 2 of 8 — Simulation"
        title="Simulation Configuration"
        description="Select a stochastic model and calibration source, then generate the Monte Carlo ensemble."
        breadcrumbs={[{ label: 'Simulations', to: '/simulation/runs' }, { label: 'Configure' }]}
      />

      <Panel title="Model">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {MODELS.map((m) => (
            <button
              key={m.id}
              onClick={() => setModel(m.id)}
              className={clsx(
                'rounded border p-4 text-left transition-colors',
                model === m.id ? 'border-[var(--color-accent)] bg-[var(--color-accent)]/8' : 'border-[var(--color-border-strong)] hover:border-[var(--color-border-strong)]/80',
              )}
            >
              <div className={clsx('text-sm font-semibold', model === m.id ? 'text-[var(--color-accent-strong)]' : 'text-[var(--color-text-primary)]')}>{m.id}</div>
              <div className="mt-1 text-xs text-[var(--color-text-muted)]">{m.description}</div>
            </button>
          ))}
        </div>
      </Panel>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        <Panel title="Run Parameters">
          <dl className="grid grid-cols-2 gap-4 text-sm">
            <div>
              <dt className="text-xs text-[var(--color-text-muted)]">Instrument</dt>
              <dd className="mono mt-0.5 text-[var(--color-text-primary)]">AAPL</dd>
            </div>
            <div>
              <dt className="text-xs text-[var(--color-text-muted)]">Calibration</dt>
              <dd className="mt-0.5 text-[var(--color-text-primary)]">{calibration.label}</dd>
            </div>
            <div>
              <dt className="text-xs text-[var(--color-text-muted)]">Paths</dt>
              <dd className="mono mt-0.5 text-[var(--color-text-primary)]">10,000</dd>
            </div>
            <div>
              <dt className="text-xs text-[var(--color-text-muted)]">Time Steps</dt>
              <dd className="mono mt-0.5 text-[var(--color-text-primary)]">252</dd>
            </div>
            <div>
              <dt className="text-xs text-[var(--color-text-muted)]">Confidence</dt>
              <dd className="mono mt-0.5 text-[var(--color-text-primary)]">95%</dd>
            </div>
          </dl>
        </Panel>

        <Panel title="Calibration Summary" subtitle={calibration.label} action={<StatusPill tone="success">{calibration.status}</StatusPill>}>
          <dl className="grid grid-cols-2 gap-4 text-sm">
            <div>
              <dt className="text-xs text-[var(--color-text-muted)]">Drift</dt>
              <dd className="mono mt-0.5 text-[var(--color-text-primary)]">{calibration.drift}</dd>
            </div>
            <div>
              <dt className="text-xs text-[var(--color-text-muted)]">Volatility</dt>
              <dd className="mono mt-0.5 text-[var(--color-text-primary)]">{calibration.volatility}</dd>
            </div>
            <div>
              <dt className="text-xs text-[var(--color-text-muted)]">Window</dt>
              <dd className="mono mt-0.5 text-[var(--color-text-primary)]">{calibration.windowDays} days</dd>
            </div>
            <div>
              <dt className="text-xs text-[var(--color-text-muted)]">Status</dt>
              <dd className="mt-0.5 text-[var(--color-text-primary)]">{calibration.status}</dd>
            </div>
          </dl>
        </Panel>
      </div>

      <div className="flex justify-end">
        <Button
          icon={ArrowRight}
          onClick={() => {
            advanceTo('SIMULATION_CONFIGURED')
            navigate('/simulation/run/1042')
          }}
        >
          Run Simulation
        </Button>
      </div>
    </div>
  )
}
