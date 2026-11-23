import { ArrowRight, RotateCcw } from 'lucide-react'
import { useNavigate, useParams } from 'react-router-dom'
import MonteCarloFanChart from '../../components/charts/MonteCarloFanChart'
import Button from '../../components/forms/Button'
import Panel from '../../components/layout/Panel'
import PageHeader from '../../components/layout/PageHeader'
import EmptyState from '../../components/status/EmptyState'
import ErrorNote from '../../components/status/ErrorNote'
import ProgressBar from '../../components/status/ProgressBar'
import StatusPill from '../../components/status/StatusPill'
import { useQuantiles, useRun } from '../../hooks/useSimulation'
import { type Run, fanOf, isRunId } from '../../services/api/simulation'

const MODEL_NAMES = { gbm: 'GBM', ou: 'Ornstein-Uhlenbeck', merton: 'Jump Diffusion' } as const
const LABEL = { queued: 'Queued', running: 'Running', completed: 'Complete', failed: 'Failed' } as const
const TONE = { queued: 'neutral', running: 'info', completed: 'success', failed: 'danger' } as const

/** What happened so far, from the run's own state (the service keeps no separate log to read). */
function events(run: Run): string[] {
  const lines = ['Run queued']
  if (run.status !== 'queued') lines.push('Worker started')
  if (run.status === 'running') lines.push(`Generating paths: ${Math.round(run.progress * 100)}%`)
  if (run.status === 'completed') {
    lines.push(`${run.n_paths.toLocaleString()} paths of ${run.n_steps} steps generated`, 'Statistics and quantiles stored')
  }
  if (run.status === 'failed') lines.push(`Failed: ${run.error ?? 'the run could not finish'}`)
  return lines
}

export default function RunSimulation() {
  const { id: param } = useParams()
  const id = isRunId(param) ? param : undefined
  const navigate = useNavigate()
  const { run, error } = useRun(id)
  const { quantiles } = useQuantiles(id, run?.status === 'completed')
  const fan = quantiles ? fanOf(quantiles) : null
  const short = (param ?? '').slice(0, 8)

  const pct = run ? Math.round((run.status === 'completed' ? 1 : run.progress) * 100) : 0
  const done = run ? Math.round(run.n_paths * (pct / 100)) : 0

  return (
    <div className="qs-fade-in flex flex-col gap-6" data-testid="page-run">
      <PageHeader
        eyebrow="Step 3 of 8 — Simulation"
        title={`Simulation #${short}`}
        description="Generating Monte Carlo Ensemble"
        breadcrumbs={[{ label: 'Simulations', to: '/simulation/runs' }, { label: `#${short}` }]}
        action={
          run && (
            <StatusPill tone={TONE[run.status]} dot>
              {LABEL[run.status]}
            </StatusPill>
          )
        }
      />

      {id === undefined ? (
        <EmptyState title="Run not found" description="This address is not a run. Open one from Simulations." />
      ) : error ? (
        <ErrorNote error={error} />
      ) : !run ? (
        <p className="text-sm text-[var(--color-text-muted)]">Loading the run…</p>
      ) : (
        <>
          <Panel>
            <div className="mb-4 flex items-center justify-between">
              <span className="text-sm font-medium text-[var(--color-text-primary)]">
                {run.status === 'completed' ? 'Simulation Complete' : run.status === 'failed' ? 'Simulation Failed' : 'Generating Monte Carlo Ensemble'}
              </span>
              <span className="mono text-sm text-[var(--color-text-secondary)]" data-testid="run-percent">
                {pct}%
              </span>
            </div>
            <ProgressBar pct={pct} />

            {run.status === 'failed' ? (
              <div role="alert" className="mt-6 rounded border border-[var(--color-risk-severe)]/40 bg-[var(--color-risk-severe)]/10 p-4">
                <div className="text-sm font-semibold text-[var(--color-risk-high)]">{run.error ?? 'The run could not finish.'}</div>
                <div className="mt-3">
                  <Button variant="secondary" icon={RotateCcw} onClick={() => navigate('/simulation/configure')}>
                    Configure again
                  </Button>
                </div>
              </div>
            ) : (
              <div className="mt-5 grid grid-cols-2 gap-4 sm:grid-cols-4">
                <Stat label="Paths generated" value={`${done.toLocaleString()} / ${run.n_paths.toLocaleString()}`} />
                <Stat label="Model" value={MODEL_NAMES[run.model]} />
                <Stat label="Instruments" value={run.symbols.join(', ')} />
                <Stat label="Steps" value={String(run.n_steps)} />
              </div>
            )}
          </Panel>

          <Panel title="Monte Carlo Ensemble" subtitle={`${run.symbols[0] ?? ''} · ${MODEL_NAMES[run.model]} · ${run.n_steps} steps`}>
            {fan ? (
              <MonteCarloFanChart bands={fan.bands} height={260} />
            ) : (
              <p className="text-sm text-[var(--color-text-muted)]" data-testid="fan-waiting">
                {run.status === 'failed' ? 'No ensemble: the run failed.' : 'The fan chart appears when the run completes.'}
              </p>
            )}
          </Panel>

          <Panel title="Event Log">
            <div className="mono flex flex-col gap-1.5 text-xs" data-testid="run-events">
              {events(run).map((message) => (
                <div key={message} className="qs-fade-in text-[var(--color-text-secondary)]">
                  {message}
                </div>
              ))}
            </div>
          </Panel>

          {run.status === 'completed' && (
            <div className="flex justify-end">
              <Button icon={ArrowRight} onClick={() => navigate(`/simulation/results/${run.id}`)}>
                View Results
              </Button>
            </div>
          )}
        </>
      )}
    </div>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs text-[var(--color-text-muted)]">{label}</div>
      <div className="mono mt-0.5 text-sm font-semibold text-[var(--color-text-primary)]">{value}</div>
    </div>
  )
}
