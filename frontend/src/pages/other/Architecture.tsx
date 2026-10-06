import clsx from 'clsx'
import { useState } from 'react'
import Modal from '../../components/modals/Modal'
import Panel from '../../components/layout/Panel'
import PageHeader from '../../components/layout/PageHeader'
import StatusPill from '../../components/status/StatusPill'

interface ServiceNode {
  id: string
  label: string
  purpose: string
  inputs: string
  outputs: string
  activity: string
}

const SERVICES: ServiceNode[] = [
  { id: 'gateway', label: 'API Gateway', purpose: 'Routes requests from the browser to backend services.', inputs: 'Authenticated HTTP requests', outputs: 'Routed service calls', activity: '1,204 requests / min' },
  { id: 'market', label: 'Market Data', purpose: 'Owns instrument reference data and historical/synthetic price series.', inputs: 'Data window, universe', outputs: 'OHLC series, instrument metadata', activity: '3 environments active' },
  { id: 'simulation', label: 'Simulation', purpose: 'Runs Monte Carlo ensembles from calibrated stochastic models.', inputs: 'Model, calibration, paths', outputs: 'Simulated price paths', activity: 'Run #1042 complete' },
  { id: 'trading', label: 'Trading', purpose: 'Executes strategies inside a simulated or replayed market.', inputs: 'Strategy, portfolio config', outputs: 'Orders, fills, portfolio state', activity: '10 fills today' },
  { id: 'ml', label: 'ML', purpose: 'Scores portfolios using trained risk and regime models.', inputs: 'Portfolio features', outputs: 'Predictions, feature attribution', activity: 'Model v1.4 in production' },
  { id: 'risk', label: 'Risk / TDA', purpose: 'Runs stress scenarios and topological structure analysis.', inputs: 'Portfolio, scenario, returns', outputs: 'Stress results, topology signal', activity: '2 analyses queued' },
  { id: 'xai', label: 'XAI', purpose: 'Generates natural-language explanations from risk signals.', inputs: 'Stress, TDA, ML outputs', outputs: 'Explanation sections, drivers', activity: 'Last run 16:22' },
  { id: 'dashboard', label: 'Dashboard', purpose: 'Aggregates composite risk and surfaces alerts to users.', inputs: 'All risk service outputs', outputs: 'Composite score, alerts', activity: '1 active alert' },
]

export default function Architecture() {
  const [active, setActive] = useState<ServiceNode | null>(null)

  const Node = ({ id }: { id: string }) => {
    const s = SERVICES.find((x) => x.id === id)!
    return (
      <button
        onClick={() => setActive(s)}
        className={clsx(
          'rounded border border-[var(--color-border-strong)] bg-[var(--color-bg-2)] px-3 py-2 text-xs font-semibold text-[var(--color-text-primary)] transition-colors hover:border-[var(--color-accent-strong)] hover:text-[var(--color-accent-strong)]',
        )}
      >
        {s.label}
      </button>
    )
  }

  return (
    <div className="qs-fade-in flex flex-col gap-6">
      <PageHeader
        title="System Architecture"
        description="Conceptual view of the QuantSim service architecture. Click a service to inspect it."
      />
      <Panel bodyClassName="p-8">
        <div className="flex flex-col items-center gap-6">
          <div className="rounded border border-[var(--color-border-strong)] bg-[var(--color-bg-2)] px-4 py-2 text-sm font-semibold">Browser</div>
          <Connector />
          <Node id="gateway" />
          <Connector />
          <div className="flex flex-wrap justify-center gap-4">
            <Node id="market" />
            <Node id="simulation" />
            <Node id="trading" />
          </div>
          <Connector label="Kafka — asynchronous event backbone" />
          <div className="flex flex-wrap justify-center gap-4">
            <Node id="ml" />
            <Node id="risk" />
            <Node id="xai" />
          </div>
          <Connector />
          <Node id="dashboard" />
        </div>
      </Panel>

      <Modal open={!!active} onClose={() => setActive(null)} title={active?.label ?? ''}>
        {active && (
          <dl className="flex flex-col gap-3 text-sm">
            <div>
              <dt className="text-xs font-medium uppercase tracking-wide text-[var(--color-text-muted)]">Purpose</dt>
              <dd className="mt-1 text-[var(--color-text-secondary)]">{active.purpose}</dd>
            </div>
            <div>
              <dt className="text-xs font-medium uppercase tracking-wide text-[var(--color-text-muted)]">Inputs</dt>
              <dd className="mt-1 text-[var(--color-text-secondary)]">{active.inputs}</dd>
            </div>
            <div>
              <dt className="text-xs font-medium uppercase tracking-wide text-[var(--color-text-muted)]">Outputs</dt>
              <dd className="mt-1 text-[var(--color-text-secondary)]">{active.outputs}</dd>
            </div>
            <div>
              <dt className="text-xs font-medium uppercase tracking-wide text-[var(--color-text-muted)]">Status</dt>
              <dd className="mt-1"><StatusPill tone="success" dot>Operational</StatusPill></dd>
            </div>
            <div>
              <dt className="text-xs font-medium uppercase tracking-wide text-[var(--color-text-muted)]">Recent Activity</dt>
              <dd className="mono mt-1 text-[var(--color-text-secondary)]">{active.activity}</dd>
            </div>
          </dl>
        )}
      </Modal>
    </div>
  )
}

function Connector({ label }: { label?: string }) {
  return (
    <div className="flex flex-col items-center">
      <div className="h-6 w-px bg-[var(--color-border-strong)]" />
      {label && <div className="mb-1 text-[10px] uppercase tracking-wide text-[var(--color-text-muted)]">{label}</div>}
    </div>
  )
}
