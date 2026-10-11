import Panel from '../../components/layout/Panel'
import PageHeader from '../../components/layout/PageHeader'
import DataTable, { type Column } from '../../components/tables/DataTable'
import StatusPill from '../../components/status/StatusPill'
import { ML_MODELS } from '../../services/mock/data'
import type { MLModelDef } from '../../types'

const columns: Column<MLModelDef>[] = [
  { key: 'name', header: 'Model', render: (r) => <span className="font-medium text-[var(--color-text-primary)]">{r.name}</span> },
  { key: 'version', header: 'Version', render: (r) => <span className="mono">{r.version}</span> },
  { key: 'task', header: 'Task', render: (r) => r.task },
  { key: 'accuracy', header: 'Accuracy', align: 'right', render: (r) => <span className="mono">{r.accuracy}%</span> },
  { key: 'trained', header: 'Last Trained', align: 'right', render: (r) => <span className="mono">{r.lastTrained}</span> },
  {
    key: 'status',
    header: 'Status',
    render: (r) => (
      <StatusPill tone={r.status === 'Production' ? 'success' : r.status === 'Staging' ? 'info' : 'neutral'} dot>
        {r.status}
      </StatusPill>
    ),
  },
]

export default function MLModelsPage() {
  return (
    <div className="qs-fade-in flex flex-col gap-6">
      <PageHeader title="ML Models" description="Registered machine learning models used across QuantSim risk intelligence." />
      <Panel bodyClassName="p-0">
        <DataTable columns={columns} rows={ML_MODELS} rowKey={(r) => r.id} />
      </Panel>
    </div>
  )
}
