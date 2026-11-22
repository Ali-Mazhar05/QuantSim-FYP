import Panel from '../../components/layout/Panel'
import PageHeader from '../../components/layout/PageHeader'
import DataTable, { type Column } from '../../components/tables/DataTable'
import EmptyState from '../../components/status/EmptyState'
import ErrorNote from '../../components/status/ErrorNote'
import StatusPill from '../../components/status/StatusPill'
import { useCalibrations } from '../../hooks/useSimulation'
import type { Calibration } from '../../services/api/simulation'

const MODEL_NAMES = { gbm: 'GBM', ou: 'Ornstein-Uhlenbeck', merton: 'Jump Diffusion' } as const

/** The fitted parameters as `name 0.62`, in the order the model declares them. */
function parameters(row: Calibration): string {
  const fit = row.calibration
  if (!fit) return ''
  return Object.entries(fit.params)
    .map(([name, value]) => `${name} ${Number(value).toPrecision(3)}`)
    .join(' · ')
}

const columns: Column<Calibration>[] = [
  {
    key: 'label',
    header: 'Calibration',
    render: (r) => (
      <span className="font-medium text-[var(--color-text-primary)]">
        {r.calibration?.symbol ?? 'Instrument'} · {r.calibration ? MODEL_NAMES[r.calibration.model] : ''}
      </span>
    ),
  },
  { key: 'instrument', header: 'Instrument', render: (r) => <span className="mono">{r.calibration?.symbol ?? '—'}</span> },
  { key: 'params', header: 'Parameters', render: (r) => <span className="mono">{parameters(r)}</span> },
  {
    key: 'window',
    header: 'Window',
    align: 'right',
    render: (r) => (
      <span className="mono">
        {r.calibration?.window_start} → {r.calibration?.window_end} · {r.calibration?.n_obs} returns
      </span>
    ),
  },
  {
    key: 'status',
    header: 'Status',
    render: (r) => (
      <StatusPill tone={r.calibration?.converged ? 'success' : 'warning'} dot>
        {r.calibration?.converged ? 'Converged' : 'Did not converge'}
      </StatusPill>
    ),
  },
]

export default function Calibrations() {
  const { calibrations, error } = useCalibrations()
  return (
    <div className="qs-fade-in flex flex-col gap-6" data-testid="page-calibrations">
      <PageHeader title="Calibrations" description="Statistical parameters fitted to historical data for each stochastic model." />
      {error ? (
        <ErrorNote error={error} />
      ) : calibrations === null ? (
        <p className="text-sm text-[var(--color-text-muted)]">Loading calibrations…</p>
      ) : calibrations.length === 0 ? (
        <EmptyState
          title="No calibrations yet"
          description="A calibration is made when a simulation is configured: the model is fitted to the environment's prices."
        />
      ) : (
        <Panel bodyClassName="p-0">
          <DataTable columns={columns} rows={calibrations} rowKey={(r) => r.id} />
        </Panel>
      )}
    </div>
  )
}
