import clsx from 'clsx'
import { Plus } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Button from '../../components/forms/Button'
import { useCan } from '../../demo/useCan'
import Panel from '../../components/layout/Panel'
import PageHeader from '../../components/layout/PageHeader'
import DataTable, { type Column } from '../../components/tables/DataTable'
import EmptyState from '../../components/status/EmptyState'
import StatusPill from '../../components/status/StatusPill'
import { listEnvironments } from '../../services/api/market'
import {
  type Portfolio,
  formatUsd,
  getMetrics,
  getRun,
  listDemoEnvironments,
  listEvents,
  listPortfolios,
  rememberedRuns,
} from './tradingApi'
import { type Failure, failureOf } from './tradingFormat'
import { FailureState, Loading } from './tradingShared'

type Tone = 'neutral' | 'success' | 'warning' | 'danger' | 'info'

/** The portfolio's last run as far as the API tells: its job when this browser started
 * it, otherwise read from the trade log (a log ends with RUN_COMPLETED once a run is done). */
interface LastRun {
  label: string
  tone: Tone
  /** Value at the last valued session; null before a run. */
  finalValue: string | null
}

const JOB_STATUS: Record<string, { label: string; tone: Tone }> = {
  queued: { label: 'Queued', tone: 'neutral' },
  running: { label: 'Running', tone: 'info' },
  succeeded: { label: 'Succeeded', tone: 'success' },
  failed: { label: 'Failed', tone: 'danger' },
}

async function lastRunOf(p: Portfolio, jobId: string | undefined): Promise<LastRun> {
  const job = jobId ? await getRun(p.id, jobId).catch(() => null) : null
  if (!p.source_fingerprint && !job) return { label: 'Not run', tone: 'neutral', finalValue: null }
  const metrics = await getMetrics(p.id)
  if (job) return { ...JOB_STATUS[job.status], finalValue: metrics.final_value }
  if (metrics.final_seq === 0) return { label: 'Not run', tone: 'neutral', finalValue: null }
  const last = await listEvents(p.id, metrics.final_seq - 1, 1)
  const completed = last.items[0]?.type === 'RUN_COMPLETED'
  return completed
    ? { label: 'Succeeded', tone: 'success', finalValue: metrics.final_value }
    : { label: 'Incomplete', tone: 'warning', finalValue: metrics.final_value }
}

interface Row {
  portfolio: Portfolio
  environment: string
  /** Undefined while loading; null when it could not be read. */
  run: LastRun | null | undefined
}

function returnOf(row: Row): number | null {
  const final = row.run?.finalValue
  if (!final) return null
  return (Number(final) / Number(row.portfolio.initial_capital) - 1) * 100
}

const columns: Column<Row>[] = [
  {
    key: 'name',
    header: 'Portfolio',
    render: (r) => (
      <span className="font-medium text-[var(--color-text-primary)]" data-testid="portfolio-row-name">
        {r.portfolio.name}
      </span>
    ),
  },
  { key: 'environment', header: 'Environment', render: (r) => r.environment },
  {
    key: 'value',
    header: 'Value',
    align: 'right',
    render: (r) => <span className="mono">{formatUsd(r.run?.finalValue ?? r.portfolio.initial_capital)}</span>,
  },
  {
    key: 'return',
    header: 'Return',
    align: 'right',
    render: (r) => {
      const pct = returnOf(r)
      if (pct === null) return <span className="mono text-[var(--color-text-muted)]">—</span>
      return (
        <span className={clsx('mono', pct >= 0 ? 'text-[var(--color-risk-low)]' : 'text-[var(--color-risk-severe)]')}>
          {pct >= 0 ? '+' : ''}
          {pct.toFixed(2)}%
        </span>
      )
    },
  },
  {
    key: 'status',
    header: 'Status',
    render: (r) =>
      r.run === undefined ? (
        <span className="text-xs text-[var(--color-text-muted)]">Checking…</span>
      ) : r.run === null ? (
        <StatusPill tone="neutral">Unknown</StatusPill>
      ) : (
        <span data-testid="portfolio-row-status">
          <StatusPill tone={r.run.tone} dot>
            {r.run.label}
          </StatusPill>
        </span>
      ),
  },
]

export default function Portfolios() {
  const navigate = useNavigate()
  const canCreate = useCan('create_portfolios')
  const [portfolios, setPortfolios] = useState<Portfolio[] | null>(null)
  const [failure, setFailure] = useState<Failure | null>(null)
  const [envNames, setEnvNames] = useState<Record<string, string>>({})
  const [runs, setRuns] = useState<Record<string, LastRun | null>>({})

  useEffect(() => {
    let cancelled = false
    listPortfolios()
      .then((rows) => {
        if (cancelled) return
        setPortfolios(rows)
        const jobs = rememberedRuns()
        for (const p of rows) {
          lastRunOf(p, jobs[p.id])
            .then((run) => !cancelled && setRuns((r) => ({ ...r, [p.id]: run })))
            .catch(() => !cancelled && setRuns((r) => ({ ...r, [p.id]: null })))
        }
      })
      .catch((error: unknown) => !cancelled && setFailure(failureOf(error)))
    // Environment names are a nicety: without them the id is shown
    Promise.all([listEnvironments().catch(() => []), listDemoEnvironments().catch(() => [])]).then(([market, demo]) => {
      if (cancelled) return
      setEnvNames(Object.fromEntries([...market, ...demo].map((e) => [e.id, e.name])))
    })
    return () => {
      cancelled = true
    }
  }, [])

  const environmentOf = (p: Portfolio): string =>
    p.env_type === 'replay'
      ? (envNames[p.replay_environment_id ?? ''] ?? `Replay ${p.replay_environment_id?.slice(0, 8)}`)
      : `Simulation ${p.simulation_run_id?.slice(0, 8)} · path ${p.path_index}`

  const rows: Row[] = (portfolios ?? []).map((p) => ({ portfolio: p, environment: environmentOf(p), run: runs[p.id] }))

  return (
    <div className="qs-fade-in flex flex-col gap-6">
      <PageHeader
        title="Portfolios"
        description="Portfolios constructed from simulated market environments."
        action={
          <Button icon={Plus} disabled={!canCreate} title={canCreate ? undefined : "Your role cannot do this"} onClick={() => navigate('/trading/portfolios/new')}>
            New Portfolio
          </Button>
        }
      />
      {failure ? (
        <FailureState failure={failure} />
      ) : portfolios === null ? (
        <Loading what="portfolios" />
      ) : portfolios.length === 0 ? (
        <EmptyState
          title="No portfolios yet"
          description={canCreate ? 'Create one with New Portfolio.' : 'A quant or an administrator creates portfolios.'}
        />
      ) : (
        <Panel bodyClassName="p-0">
          <DataTable columns={columns} rows={rows} rowKey={(r) => r.portfolio.id} onRowClick={(r) => navigate(`/trading/replay/${r.portfolio.id}`)} />
        </Panel>
      )}
    </div>
  )
}
