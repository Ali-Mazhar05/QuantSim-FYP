import { Plus } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import DataTable, { type Column } from '../../components/tables/DataTable'
import Button from '../../components/forms/Button'
import { useCan } from '../../demo/useCan'
import Panel from '../../components/layout/Panel'
import PageHeader from '../../components/layout/PageHeader'
import EmptyState from '../../components/status/EmptyState'
import StatusPill from '../../components/status/StatusPill'
import { useEnvironments } from '../../hooks/useEnvironments'
import type { MarketEnvironment } from '../../types'

const columns: Column<MarketEnvironment>[] = [
  { key: 'name', header: 'Environment', render: (r) => <span className="font-medium text-[var(--color-text-primary)]">{r.name}</span> },
  { key: 'type', header: 'Type', render: (r) => r.type },
  { key: 'universe', header: 'Universe', render: (r) => r.universe },
  { key: 'window', header: 'Window', render: (r) => <span className="mono">{r.start} → {r.end}</span> },
  { key: 'freq', header: 'Frequency', render: (r) => r.frequency },
  {
    key: 'status',
    header: 'Status',
    render: (r) => (
      <StatusPill tone={r.status === 'Active' ? 'success' : r.status === 'Ready' ? 'info' : 'neutral'} dot>
        {r.status}
      </StatusPill>
    ),
  },
]

export default function MarketEnvironmentsList() {
  const navigate = useNavigate()
  const canCreate = useCan('create_market_environments')
  const { environments, error } = useEnvironments()
  return (
    <div className="qs-fade-in flex flex-col gap-6">
      <PageHeader
        title="Market Environments"
        description="Historical replays and synthetic markets available for simulation."
        action={
          <Button icon={Plus} disabled={!canCreate} title={canCreate ? undefined : "Your role cannot do this"} onClick={() => navigate('/market/environments/new')}>
            New Environment
          </Button>
        }
      />
      {error ? (
        <p role="alert" className="text-sm text-[var(--color-risk-severe)]">
          {error.message}
        </p>
      ) : environments === null ? (
        <p className="text-sm text-[var(--color-text-muted)]">Loading environments…</p>
      ) : environments.length === 0 ? (
        <EmptyState title="No environments yet" description="A quant or an administrator creates the first one with New Environment." />
      ) : (
        <Panel bodyClassName="p-0">
          <DataTable
            columns={columns}
            rows={environments}
            rowKey={(r) => r.id}
            onRowClick={canCreate ? () => navigate('/market/environments/new') : undefined}
          />
        </Panel>
      )}
    </div>
  )
}
