import { ArrowRight, Zap } from 'lucide-react'
import { useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import MonteCarloFanChart from '../../components/charts/MonteCarloFanChart'
import Button from '../../components/forms/Button'
import Panel from '../../components/layout/Panel'
import PageHeader from '../../components/layout/PageHeader'
import EmptyState from '../../components/status/EmptyState'
import ErrorNote from '../../components/status/ErrorNote'
import StatusPill from '../../components/status/StatusPill'
import DataTable, { type Column } from '../../components/tables/DataTable'
import { useCan } from '../../demo/useCan'
import { classifyError } from '../../hooks/apiError'
import { useQuantiles, useRun, useRuns, useScenarios, useStressRun } from '../../hooks/useSimulation'
import { type Run, fanOf, isRunId } from '../../services/api/simulation'

const MODEL_NAMES = { gbm: 'GBM', ou: 'Ornstein-Uhlenbeck', merton: 'Jump Diffusion' } as const
type Statistic = Run['statistics'][number]

const money = (value: string) => `$${Number(value).toFixed(2)}`
/** A loss is a positive fraction on the wire; it is shown as a negative percentage. */
const loss = (value: string) => `-${(Number(value) * 100).toFixed(1)}%`

const columns: Column<Statistic>[] = [
  { key: 'symbol', header: 'Instrument', render: (s) => <span className="mono font-semibold">{s.symbol}</span> },
  { key: 'mean', header: 'Mean', align: 'right', render: (s) => <span className="mono">{money(s.mean_price)}</span> },
  { key: 'median', header: 'Median', align: 'right', render: (s) => <span className="mono">{money(s.median_price)}</span> },
  { key: 'p5', header: '5th %ile', align: 'right', render: (s) => <span className="mono">{money(s.p5_price)}</span> },
  { key: 'p95', header: '95th %ile', align: 'right', render: (s) => <span className="mono">{money(s.p95_price)}</span> },
  {
    key: 'var',
    header: 'VaR 95%',
    align: 'right',
    render: (s) => <span className="mono text-[var(--color-risk-severe)]">{loss(s.var95)}</span>,
  },
  {
    key: 'cvar',
    header: 'CVaR 95%',
    align: 'right',
    render: (s) => <span className="mono text-[var(--color-risk-severe)]">{loss(s.cvar95)}</span>,
  },
]

export default function SimulationResults() {
  const { id: param } = useParams()
  const id = isRunId(param) ? param : undefined
  const navigate = useNavigate()
  const canCreate = useCan('create_portfolios')
  const canLaunch = useCan('launch_simulations')
  const { run, error } = useRun(id)
  const { quantiles } = useQuantiles(id, run?.status === 'completed')
  const { runs } = useRuns()
  const { scenarios } = useScenarios()
  const stress = useStressRun()
  const [problem, setProblem] = useState<string | null>(null)
  const keys = useRef(new Map<string, string>())

  // the run this one is compared with: its parent (when it is stressed) or its stressed copy
  const other = run
    ? run.parent_run_id
      ? runs?.find((r) => r.id === run.parent_run_id)
      : runs?.find((r) => r.parent_run_id === run.id && r.status === 'completed')
    : undefined
  const { quantiles: otherQuantiles } = useQuantiles(other?.id, Boolean(other))
  const fan = quantiles ? fanOf(quantiles) : null
  const otherFan = otherQuantiles ? fanOf(otherQuantiles, fan ? quantiles?.instruments[0]?.instrument_id : undefined) : null
  const short = (param ?? '').slice(0, 8)

  async function apply(code: string) {
    if (!run) return
    setProblem(null)
    // one key per run and scenario: a double click asks for one stressed run
    const k = `${run.id}:${code}`
    if (!keys.current.has(k)) keys.current.set(k, crypto.randomUUID())
    try {
      const derived = await stress.mutateAsync({ runId: run.id, scenario: code, key: keys.current.get(k) as string })
      navigate(`/simulation/run/${derived.id}`)
    } catch (failure) {
      setProblem(classifyError(failure).message)
    }
  }

  return (
    <div className="qs-fade-in flex flex-col gap-6" data-testid="page-results">
      <PageHeader
        eyebrow="Step 4 of 8 — Simulation"
        title={`Simulation #${short}`}
        breadcrumbs={[{ label: 'Simulations', to: '/simulation/runs' }, { label: `#${short}` }]}
        description={
          run
            ? `${MODEL_NAMES[run.model]} · ${run.symbols.join(', ')} · ${run.n_paths.toLocaleString()} paths · ${run.n_steps} steps${run.scenario ? ` · scenario ${run.scenario}` : ''}`
            : undefined
        }
        action={
          run && (
            <StatusPill tone={run.status === 'completed' ? 'success' : run.status === 'failed' ? 'danger' : 'info'} dot>
              {run.status === 'completed' ? 'Complete' : run.status === 'failed' ? 'Failed' : 'Not finished'}
            </StatusPill>
          )
        }
      />

      {id === undefined ? (
        <EmptyState title="Run not found" description="This address is not a run. Open one from Simulations." />
      ) : error ? (
        <ErrorNote error={error} />
      ) : !run ? (
        <p className="text-sm text-[var(--color-text-muted)]">Loading the results…</p>
      ) : run.status !== 'completed' ? (
        <Panel>
          <p role="status" className="text-sm text-[var(--color-text-secondary)]">
            {run.status === 'failed' ? `This run failed: ${run.error ?? 'no reason was recorded'}.` : 'This run has not finished, so it has no results yet.'}{' '}
            <button className="underline" onClick={() => navigate(`/simulation/run/${run.id}`)}>
              Open the run
            </button>
          </p>
        </Panel>
      ) : (
        <>
          <Panel
            title="Monte Carlo Fan Chart"
            subtitle={fan ? `${fan.symbol}: simulated price quantiles by step` : 'Simulated price quantiles by step'}
          >
            {fan ? (
              <MonteCarloFanChart
                bands={fan.bands}
                height={320}
                {...(otherFan
                  ? {
                      compare: otherFan.bands.p50,
                      compareLabel: run.parent_run_id ? 'Base median' : `Stressed median (${other?.scenario ?? 'scenario'})`,
                    }
                  : {})}
              />
            ) : (
              <p className="text-sm text-[var(--color-text-muted)]">Loading the fan chart…</p>
            )}
          </Panel>

          <Panel title="Terminal Price and Risk" subtitle="At the last step, over all paths">
            <DataTable columns={columns} rows={run.statistics} rowKey={(s) => s.instrument_id} />
          </Panel>

          {other && (
            <Panel title={run.parent_run_id ? 'Base Run' : 'Stressed Run'} subtitle={`${other.scenario ?? 'base'} · #${other.id.slice(0, 8)}`}>
              <p className="text-sm text-[var(--color-text-secondary)]" data-testid="compare-note">
                {run.parent_run_id
                  ? 'The dashed line is the median of the base run this one was stressed from.'
                  : `The dashed line is the median of the stressed copy (${other.scenario}) of this run.`}{' '}
                <button className="underline" onClick={() => navigate(`/simulation/results/${other.id}`)}>
                  Open it
                </button>
              </p>
            </Panel>
          )}

          {!run.parent_run_id && (
            <Panel title="Stress Scenarios" subtitle="A stressed copy uses this run's seed and parameters, with the scenario on top">
              {scenarios === null ? (
                <p className="text-sm text-[var(--color-text-muted)]">Loading scenarios…</p>
              ) : scenarios.length === 0 ? (
                <p className="text-sm text-[var(--color-text-muted)]">There are no scenarios yet.</p>
              ) : (
                <div className="flex flex-wrap gap-3">
                  {scenarios.map((s) => (
                    <Button
                      key={s.code}
                      variant="secondary"
                      icon={Zap}
                      disabled={!canLaunch || stress.isPending}
                      data-testid={`stress-${s.code}`}
                      onClick={() => void apply(s.code)}
                    >
                      {s.name}
                    </Button>
                  ))}
                </div>
              )}
              {!canLaunch && <p className="mt-3 text-xs text-[var(--color-text-muted)]">Your role can read results but not start a stressed run.</p>}
              {problem && (
                <p role="alert" className="mt-3 text-sm text-[var(--color-risk-severe)]">
                  {problem}
                </p>
              )}
            </Panel>
          )}

          {!canCreate && (
            <p className="text-sm text-[var(--color-text-muted)]">Your role can read results but not create a portfolio.</p>
          )}
          <div className="flex justify-end">
            <Button icon={ArrowRight} disabled={!canCreate} onClick={() => navigate(`/trading/portfolios/new?run=${run.id}`)}>
              Create Portfolio
            </Button>
          </div>
        </>
      )}
    </div>
  )
}
