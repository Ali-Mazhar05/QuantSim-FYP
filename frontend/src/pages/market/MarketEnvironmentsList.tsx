import { Plus } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import DataTable, { type Column } from '../../components/tables/DataTable'
import Button from '../../components/forms/Button'
import Panel from '../../components/layout/Panel'
import PageHeader from '../../components/layout/PageHeader'
import StatusPill from '../../components/status/StatusPill'
import { MARKET_ENVIRONMENTS } from '../../services/mock/data'
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
  return (
    <div className="qs-fade-in flex flex-col gap-6">
      <PageHeader
        title="Market Environments"
        description="Historical replays and synthetic markets available for simulation."
        action={
          <Button icon={Plus} onClick={() => navigate('/market/environments/new')}>
            New Environment
          </Button>
        }
      />
      <Panel bodyClassName="p-0">
        <DataTable
          columns={columns}
          rows={MARKET_ENVIRONMENTS}
          rowKey={(r) => r.id}
          onRowClick={() => navigate('/market/environments/new')}
        />
      </Panel>
    </div>
  )
}
