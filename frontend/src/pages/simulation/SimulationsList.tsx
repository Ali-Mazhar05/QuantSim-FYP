import { Plus } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import Button from '../../components/forms/Button'
import { useCan } from '../../demo/useCan'
import Panel from '../../components/layout/Panel'
import PageHeader from '../../components/layout/PageHeader'
import DataTable, { type Column } from '../../components/tables/DataTable'
import StatusPill from '../../components/status/StatusPill'
import { useDemoStore } from '../../demo/demoState'

interface Row {
  id: string
  model: string
  instrument: string
  paths: number
  status: string
}

export default function SimulationsList() {
  const navigate = useNavigate()
  const canLaunch = useCan('launch_simulations')
  const hasReached = useDemoStore((s) => s.hasReached)
  const rows: Row[] = [
    { id: '1042', model: 'GBM', instrument: 'AAPL', paths: 10000, status: hasReached('SIMULATION_COMPLETE') ? 'Complete' : 'Configured' },
    { id: '1041', model: 'Jump Diffusion', instrument: 'NVDA', paths: 5000, status: 'Complete' },
    { id: '1040', model: 'GBM', instrument: 'MSFT', paths: 10000, status: 'Complete' },
    { id: '1039', model: 'Regime Switching', instrument: 'TSLA', paths: 8000, status: 'Failed' },
  ]

  const columns: Column<Row>[] = [
    { key: 'id', header: 'Run', render: (r) => <span className="mono font-semibold text-[var(--color-text-primary)]">#{r.id}</span> },
    { key: 'model', header: 'Model', render: (r) => r.model },
    { key: 'instrument', header: 'Instrument', render: (r) => <span className="mono">{r.instrument}</span> },
    { key: 'paths', header: 'Paths', align: 'right', render: (r) => <span className="mono">{r.paths.toLocaleString()}</span> },
    {
      key: 'status',
      header: 'Status',
      render: (r) => (
        <StatusPill tone={r.status === 'Complete' ? 'success' : r.status === 'Failed' ? 'danger' : 'info'} dot>
          {r.status}
        </StatusPill>
      ),
    },
  ]

  return (
    <div className="qs-fade-in flex flex-col gap-6">
      <PageHeader
        title="Simulations"
        description="Monte Carlo simulation runs across market environments."
        action={
          <Button icon={Plus} disabled={!canLaunch} title={canLaunch ? undefined : "Your role cannot do this"} onClick={() => navigate('/simulation/configure')}>
            New Simulation
          </Button>
        }
      />
      <Panel bodyClassName="p-0">
        <DataTable
          columns={columns}
          rows={rows}
          rowKey={(r) => r.id}
          onRowClick={(r) => navigate(r.status === 'Complete' ? `/simulation/results/${r.id}` : `/simulation/run/${r.id}`)}
        />
      </Panel>
    </div>
  )
}
