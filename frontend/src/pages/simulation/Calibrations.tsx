import Panel from '../../components/layout/Panel'
import PageHeader from '../../components/layout/PageHeader'
import DataTable, { type Column } from '../../components/tables/DataTable'
import StatusPill from '../../components/status/StatusPill'
import { CALIBRATIONS } from '../../services/mock/data'
import type { Calibration } from '../../types'

const columns: Column<Calibration>[] = [
  { key: 'label', header: 'Calibration', render: (r) => <span className="font-medium text-[var(--color-text-primary)]">{r.label}</span> },
  { key: 'instrument', header: 'Instrument', render: (r) => <span className="mono">{r.instrument}</span> },
  { key: 'drift', header: 'Drift', align: 'right', render: (r) => <span className="mono">{r.drift}</span> },
  { key: 'vol', header: 'Volatility', align: 'right', render: (r) => <span className="mono">{r.volatility}</span> },
  { key: 'window', header: 'Window', align: 'right', render: (r) => <span className="mono">{r.windowDays}d</span> },
  {
    key: 'status',
    header: 'Status',
    render: (r) => (
      <StatusPill tone={r.status === 'Valid' ? 'success' : r.status === 'Stale' ? 'warning' : 'danger'} dot>
        {r.status}
      </StatusPill>
    ),
  },
]

export default function Calibrations() {
  return (
    <div className="qs-fade-in flex flex-col gap-6">
      <PageHeader title="Calibrations" description="Statistical parameters fitted to historical data for each stochastic model." />
      <Panel bodyClassName="p-0">
        <DataTable columns={columns} rows={CALIBRATIONS} rowKey={(r) => r.id} />
      </Panel>
    </div>
  )
}
