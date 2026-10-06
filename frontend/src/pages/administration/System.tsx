import Panel from '../../components/layout/Panel'
import PageHeader from '../../components/layout/PageHeader'
import StatusPill from '../../components/status/StatusPill'

const SERVICES = [
  { name: 'API Gateway', status: 'Operational' },
  { name: 'Market Data', status: 'Operational' },
  { name: 'Simulation', status: 'Operational' },
  { name: 'Trading', status: 'Operational' },
  { name: 'ML', status: 'Operational' },
  { name: 'Risk / TDA', status: 'Operational' },
  { name: 'XAI', status: 'Operational' },
  { name: 'Event Backbone', status: 'Operational' },
]

export default function System() {
  return (
    <div className="qs-fade-in flex flex-col gap-6">
      <PageHeader title="System" description="Platform configuration and service health overview." />
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {SERVICES.map((s) => (
          <div key={s.name} className="qs-panel flex items-center justify-between rounded p-4">
            <span className="text-sm font-medium text-[var(--color-text-primary)]">{s.name}</span>
            <StatusPill tone="success" dot>{s.status}</StatusPill>
          </div>
        ))}
      </div>
      <Panel title="Environment">
        <dl className="grid grid-cols-2 gap-4 text-sm sm:grid-cols-4">
          <div>
            <dt className="text-xs text-[var(--color-text-muted)]">Environment</dt>
            <dd className="mt-0.5 text-[var(--color-text-primary)]">Research</dd>
          </div>
          <div>
            <dt className="text-xs text-[var(--color-text-muted)]">Version</dt>
            <dd className="mono mt-0.5 text-[var(--color-text-primary)]">poc-1.0.0</dd>
          </div>
          <div>
            <dt className="text-xs text-[var(--color-text-muted)]">Region</dt>
            <dd className="mt-0.5 text-[var(--color-text-primary)]">us-east-1</dd>
          </div>
          <div>
            <dt className="text-xs text-[var(--color-text-muted)]">Mode</dt>
            <dd className="mt-0.5 text-[var(--color-text-primary)]">Demo</dd>
          </div>
        </dl>
      </Panel>
    </div>
  )
}
