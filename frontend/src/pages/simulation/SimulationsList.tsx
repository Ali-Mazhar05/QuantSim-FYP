import { Plus } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import Button from '../../components/forms/Button'
import Panel from '../../components/layout/Panel'
import PageHeader from '../../components/layout/PageHeader'
import EmptyState from '../../components/status/EmptyState'
import ErrorNote from '../../components/status/ErrorNote'
import StatusPill from '../../components/status/StatusPill'
import DataTable, { type Column } from '../../components/tables/DataTable'
import { useCan } from '../../demo/useCan'
import { useRuns } from '../../hooks/useSimulation'
import type { RunSummary } from '../../services/api/simulation'

const MODEL_NAMES = { gbm: 'GBM', ou: 'Ornstein-Uhlenbeck', merton: 'Jump Diffusion' } as const
const STATUS: Record<RunSummary['status'], { label: string; tone: 'success' | 'danger' | 'info' | 'neutral' }> = {
  completed: { label: 'Complete', tone: 'success' },
  failed: { label: 'Failed', tone: 'danger' },
  running: { label: 'Running', tone: 'info' },
  queued: { label: 'Queued', tone: 'neutral' },
}

/** The first eight characters of the id: enough to tell runs apart in a list. */
const shortId = (id: string) => id.slice(0, 8)

const columns: Column<RunSummary>[] = [
  {
    key: 'id',
    header: 'Run',
    render: (r) => <span className="mono font-semibold text-[var(--color-text-primary)]">#{shortId(r.id)}</span>,
  },
  { key: 'model', header: 'Model', render: (r) => MODEL_NAMES[r.model] },
  { key: 'instrument', header: 'Instruments', render: (r) => <span className="mono">{r.symbols.join(', ')}</span> },
  {
    key: 'scenario',
    header: 'Scenario',
    render: (r) => (r.scenario ? <span className="mono">{r.scenario}</span> : <span className="text-[var(--color-text-muted)]">Base</span>),
  },
  { key: 'paths', header: 'Paths', align: 'right', render: (r) => <span className="mono">{r.n_paths.toLocaleString()}</span> },
  {
    key: 'status',
    header: 'Status',
    render: (r) => (
      <StatusPill tone={STATUS[r.status].tone} dot>
        {STATUS[r.status].label}
      </StatusPill>
    ),
  },
]

export default function SimulationsList() {
  const navigate = useNavigate()
  const canLaunch = useCan('launch_simulations')
  const { runs, error } = useRuns()

  return (
    <div className="qs-fade-in flex flex-col gap-6" data-testid="page-simulations">
      <PageHeader
        title="Simulations"
        description="Monte Carlo simulation runs across market environments."
        action={
          <Button
            icon={Plus}
            disabled={!canLaunch}
            title={canLaunch ? undefined : 'Your role cannot do this'}
            onClick={() => navigate('/simulation/configure')}
          >
            New Simulation
          </Button>
        }
      />
      {!canLaunch && (
        <p className="text-xs text-[var(--color-text-muted)]">Your role can read simulations but not start one.</p>
      )}
      {error ? (
        <ErrorNote error={error} />
      ) : runs === null ? (
        <p className="text-sm text-[var(--color-text-muted)]">Loading simulations…</p>
      ) : runs.length === 0 ? (
        <EmptyState title="No simulations yet" description="A quant or an administrator starts the first one with New Simulation." />
      ) : (
        <Panel bodyClassName="p-0">
          <DataTable
            columns={columns}
            rows={runs}
            rowKey={(r) => r.id}
            onRowClick={(r) => navigate(r.status === 'completed' ? `/simulation/results/${r.id}` : `/simulation/run/${r.id}`)}
          />
        </Panel>
      )}
    </div>
  )
}
