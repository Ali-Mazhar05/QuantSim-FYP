import { ArrowRight, Play, Plus } from 'lucide-react'
import { type ReactNode, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Button from '../../components/forms/Button'
import Panel from '../../components/layout/Panel'
import PageHeader from '../../components/layout/PageHeader'
import EmptyState from '../../components/status/EmptyState'
import StatusPill from '../../components/status/StatusPill'
import { useDemoStore } from '../../demo/demoState'
import { ApiError } from '../../services/api/client'
import { type Environment, listEnvironments } from '../../services/api/market'
import {
  type DemoEnvironment,
  type Portfolio,
  type Run,
  type RunStatus,
  type SlippageModel,
  type Strategy,
  createPortfolio,
  formatFraction,
  formatUsd,
  RUN_POLL_MS,
  getRun,
  listDemoEnvironments,
  listStrategies,
  rememberRun,
  startRun,
} from './tradingApi'
import { type Failure, failureOf, strategyRules } from './tradingFormat'
import { ErrorNotice, FailureState, Loading } from './tradingShared'

const RUN_TONES: Record<RunStatus, 'info' | 'success' | 'danger' | 'neutral'> = {
  queued: 'neutral',
  running: 'info',
  succeeded: 'success',
  failed: 'danger',
}
const RUN_LABELS: Record<RunStatus, string> = { queued: 'Queued', running: 'Running', succeeded: 'Succeeded', failed: 'Failed' }

const INPUT =
  'rounded border border-[var(--color-border-strong)] bg-[var(--color-bg-2)] px-3 py-1.5 text-sm text-[var(--color-text-primary)] focus:border-[var(--color-accent-strong)] focus:outline-none'

function Field({ label, error, field, children }: { label: ReactNode; error?: string; field: string; children: ReactNode }) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="text-xs text-[var(--color-text-muted)]">{label}</span>
      {children}
      {error && (
        <span className="text-xs text-[var(--color-risk-severe)]" data-testid={`field-error-${field}`}>
          {error}
        </span>
      )}
    </label>
  )
}

/** Field -> message from a 422; a nested field's message names its path. */
function fieldErrorsOf(error: ApiError): Record<string, string> {
  const result: Record<string, string> = {}
  const errors = Array.isArray(error.body.errors) ? (error.body.errors as { location?: unknown[]; message?: unknown }[]) : []
  for (const entry of errors) {
    const location = (Array.isArray(entry.location) ? entry.location : []).slice(1).map(String)
    const field = location[0] ?? 'body'
    const rest = location.slice(1).join('.')
    if (typeof entry.message === 'string' && !(field in result)) result[field] = rest ? `${rest}: ${entry.message}` : entry.message
  }
  return result
}

interface Loaded {
  strategies: Strategy[]
  /** Market replay environments; empty when they could not be loaded. */
  environments: Environment[]
  /** The bundled demo environments (DEV only). */
  demo: DemoEnvironment[]
  /** Why the environments could not be loaded, if they could not. */
  environmentsError: string | null
}

export default function CreatePortfolio() {
  const navigate = useNavigate()
  const advanceTo = useDemoStore((s) => s.advanceTo)

  const [loaded, setLoaded] = useState<Loaded | null>(null)
  const [failure, setFailure] = useState<Failure | null>(null)

  const [strategyId, setStrategyId] = useState('')
  const [name, setName] = useState('')
  const [capital, setCapital] = useState('1000000')
  const [environment, setEnvironment] = useState('')
  const [fixed, setFixed] = useState('0')
  const [perShare, setPerShare] = useState('0')
  const [pct, setPct] = useState('0.0005')
  const [slippageKind, setSlippageKind] = useState<SlippageModel['kind']>('fixed_bps')
  const [bps, setBps] = useState('2')

  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)
  const [created, setCreated] = useState<Portfolio | null>(null)
  const [run, setRun] = useState<Run | null>(null)
  const [starting, setStarting] = useState(false)
  const [runError, setRunError] = useState<string | null>(null)
  const pollTimer = useRef<number | null>(null)

  useEffect(() => {
    let cancelled = false
    // A failed environment list is reported in the picker; the page still loads
    let environmentsError: string | null = null
    const remember = (error: unknown) => {
      environmentsError ??= failureOf(error).message
      return []
    }
    const market = listEnvironments().catch((error: unknown): Environment[] => remember(error))
    const demo = listDemoEnvironments().catch((error: unknown): DemoEnvironment[] => remember(error))
    Promise.all([listStrategies(), market, demo])
      .then(([strategies, environments, demoEnvironments]) => {
        if (cancelled) return
        setLoaded({ strategies, environments, demo: demoEnvironments, environmentsError })
        if (strategies.length > 0) setStrategyId(strategies[0].id)
      })
      .catch((error: unknown) => !cancelled && setFailure(failureOf(error)))
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(
    () => () => {
      if (pollTimer.current !== null) window.clearTimeout(pollTimer.current)
    },
    [],
  )

  const strategy = loaded?.strategies.find((s) => s.id === strategyId) ?? null

  const submit = async () => {
    if (!strategy) return
    setCreating(true)
    setFieldErrors({})
    setSubmitError(null)
    try {
      const portfolio = await createPortfolio({
        name: name.trim(),
        strategy_id: strategy.id,
        initial_capital: capital.trim(),
        cost_model: { fixed: fixed.trim(), per_share: perShare.trim(), pct: pct.trim() },
        slippage_model: { kind: slippageKind, bps: bps.trim() },
        replay_environment_id: environment.replace(/^replay:/, ''),
      })
      setCreated(portfolio)
      advanceTo('PORTFOLIO_CREATED')
    } catch (error: unknown) {
      if (error instanceof ApiError && error.status === 422) {
        const fields = fieldErrorsOf(error)
        setFieldErrors(fields)
        setSubmitError(`Check the highlighted fields: ${error.message}`)
      } else {
        setSubmitError(failureOf(error).message)
      }
    } finally {
      setCreating(false)
    }
  }

  const poll = (portfolioId: string, jobId: string) => {
    pollTimer.current = window.setTimeout(() => {
      getRun(portfolioId, jobId)
        .then((state) => {
          setRun(state)
          setRunError(null)
          if (state.status === 'queued' || state.status === 'running') poll(portfolioId, jobId)
        })
        .catch((error: unknown) => {
          setRunError(failureOf(error).message)
          poll(portfolioId, jobId)
        })
    }, RUN_POLL_MS)
  }

  const follow = (portfolioId: string, jobId: string, status: RunStatus) => {
    rememberRun(portfolioId, jobId)
    setRun((current) => current ?? ({ job_id: jobId, portfolio_id: portfolioId, status, progress: 0 } as Run))
    if (status === 'queued' || status === 'running') poll(portfolioId, jobId)
    else
      void getRun(portfolioId, jobId)
        .then(setRun)
        .catch(() => undefined)
  }

  const runBacktest = async () => {
    if (!created) return
    setStarting(true)
    setRunError(null)
    try {
      const accepted = await startRun(created.id)
      follow(created.id, accepted.job_id, accepted.status)
    } catch (error: unknown) {
      const inProgress = error instanceof ApiError && error.status === 409 && typeof error.body.job_id === 'string'
      if (inProgress) follow(created.id, error.body.job_id as string, 'running')
      else setRunError(failureOf(error).message)
    } finally {
      setStarting(false)
    }
  }

  const weights = strategy?.kind === 'buy_and_hold' ? (strategy.params.weights as Record<string, unknown> | null | undefined) : null
  const canSubmit = !!strategy && !!name.trim() && !!environment && !created

  return (
    <div className="qs-fade-in flex flex-col gap-6">
      <PageHeader
        eyebrow="Step 5 of 8 — Trading"
        title="Create Portfolio"
        breadcrumbs={[{ label: 'Portfolios', to: '/trading/portfolios' }, { label: 'New' }]}
      />

      {failure ? (
        <FailureState failure={failure} />
      ) : loaded === null ? (
        <Loading what="strategies and environments" />
      ) : loaded.strategies.length === 0 ? (
        <EmptyState
          title="No strategies yet"
          description="A portfolio runs one strategy. Create a strategy first."
          action={
            <Button size="sm" icon={Plus} onClick={() => navigate('/trading/strategies/new')}>
              New Strategy
            </Button>
          }
        />
      ) : (
        <>
          <Panel title="Strategy" subtitle={strategy?.name}>
            <Field label="Strategy" error={fieldErrors.strategy_id} field="strategy_id">
              <select
                value={strategyId}
                onChange={(e) => setStrategyId(e.target.value)}
                disabled={!!created}
                className={`${INPUT} max-w-md`}
                data-testid="portfolio-strategy"
              >
                {loaded.strategies.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </select>
            </Field>
            {strategy && (
              <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-[var(--color-text-secondary)]">
                {strategyRules(strategy).map((d) => (
                  <li key={d}>{d}</li>
                ))}
              </ul>
            )}
          </Panel>

          <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
            <Panel title="Portfolio">
              <div className="grid grid-cols-2 gap-4 text-sm">
                <div className="col-span-2">
                  <Field label="Portfolio Name" error={fieldErrors.name} field="name">
                    <input
                      value={name}
                      onChange={(e) => setName(e.target.value)}
                      disabled={!!created}
                      placeholder="e.g. Momentum on 2024 replay"
                      className={INPUT}
                      data-testid="portfolio-name"
                    />
                  </Field>
                </div>
                <Field label="Starting Capital (USD)" error={fieldErrors.initial_capital} field="initial_capital">
                  <input
                    value={capital}
                    onChange={(e) => setCapital(e.target.value)}
                    disabled={!!created}
                    inputMode="decimal"
                    className={`${INPUT} mono`}
                    data-testid="portfolio-capital"
                  />
                </Field>
                <div>
                  <dt className="text-xs text-[var(--color-text-muted)]">Base Currency</dt>
                  <dd className="mono mt-1.5 text-base font-semibold text-[var(--color-text-primary)]">USD</dd>
                </div>
                <div className="col-span-2">
                  <Field
                    label="Market Environment"
                    error={fieldErrors.replay_environment_id ?? fieldErrors.simulation_run_id ?? fieldErrors.path_index}
                    field="environment"
                  >
                    <select
                      value={environment}
                      onChange={(e) => setEnvironment(e.target.value)}
                      disabled={!!created}
                      className={INPUT}
                      data-testid="portfolio-environment"
                    >
                      <option value="">Choose an environment…</option>
                      <optgroup label="Market replay environments">
                        {loaded.environments.map((e) => (
                          <option key={e.id} value={`replay:${e.id}`}>
                            {e.name} ({e.start} – {e.end})
                          </option>
                        ))}
                      </optgroup>
                      {loaded.demo.length > 0 && (
                        <optgroup label="Demo environments">
                          {loaded.demo.map((e) => (
                            <option key={e.id} value={`replay:${e.id}`}>
                              {e.name} ({e.sessions} sessions)
                            </option>
                          ))}
                        </optgroup>
                      )}
                      <optgroup label="Simulation runs">
                        <option value="" disabled>
                          No simulation runs available yet
                        </option>
                      </optgroup>
                    </select>
                  </Field>
                  <p className="mt-1.5 text-xs text-[var(--color-text-muted)]">
                    Simulation runs will be listed here once the simulation service publishes its run list.
                  </p>
                  {loaded.environmentsError && <ErrorNotice message={`Market environments: ${loaded.environmentsError}`} />}
                </div>
              </div>

              <div className="mt-5">
                <div className="mb-2 text-xs font-medium uppercase tracking-wide text-[var(--color-text-muted)]">Positions</div>
                {weights ? (
                  <div className="flex flex-col gap-2">
                    {Object.entries(weights).map(([symbol, w]) => (
                      <div key={symbol} className="flex items-center gap-3">
                        <span className="mono w-14 text-sm font-medium text-[var(--color-text-primary)]">{symbol}</span>
                        <div className="h-2 flex-1 overflow-hidden rounded bg-[var(--color-bg-3)]">
                          <div className="h-full rounded bg-[var(--color-accent)]" style={{ width: formatFraction(w) }} />
                        </div>
                        <span className="mono w-14 text-right text-sm text-[var(--color-text-secondary)]">{formatFraction(w)}</span>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-sm text-[var(--color-text-secondary)]">Set by the strategy over the environment's symbols when the portfolio runs.</p>
                )}
              </div>
            </Panel>

            <Panel title="Execution Assumptions">
              <div className="grid grid-cols-2 gap-4 text-sm">
                <div className="col-span-2 text-xs font-medium uppercase tracking-wide text-[var(--color-text-muted)]">Transaction Cost</div>
                <Field label="Fixed per Fill (USD)" error={fieldErrors.cost_model} field="cost_model">
                  <input value={fixed} onChange={(e) => setFixed(e.target.value)} disabled={!!created} inputMode="decimal" className={`${INPUT} mono`} />
                </Field>
                <Field label="Per Share (USD)" field="per_share">
                  <input value={perShare} onChange={(e) => setPerShare(e.target.value)} disabled={!!created} inputMode="decimal" className={`${INPUT} mono`} />
                </Field>
                <Field label={`Of Notional (fraction, ${formatFraction(pct)})`} field="pct">
                  <input value={pct} onChange={(e) => setPct(e.target.value)} disabled={!!created} inputMode="decimal" className={`${INPUT} mono`} />
                </Field>
                <div />
                <div className="col-span-2 text-xs font-medium uppercase tracking-wide text-[var(--color-text-muted)]">Slippage</div>
                <Field label="Model" error={fieldErrors.slippage_model} field="slippage_model">
                  <select
                    value={slippageKind}
                    onChange={(e) => setSlippageKind(e.target.value as SlippageModel['kind'])}
                    disabled={!!created}
                    className={INPUT}
                  >
                    <option value="fixed_bps">Fixed basis points</option>
                    <option value="volume">Volume based</option>
                  </select>
                </Field>
                <Field label="Basis Points" field="bps">
                  <input value={bps} onChange={(e) => setBps(e.target.value)} disabled={!!created} inputMode="decimal" className={`${INPUT} mono`} />
                </Field>
              </div>
            </Panel>
          </div>

          {submitError && <ErrorNotice message={submitError} />}

          {created ? (
            <Panel title="Backtest" subtitle={`${created.name} · ${formatUsd(created.initial_capital)} on ${created.strategy_name}`}>
              <div className="flex flex-wrap items-center gap-3">
                {run ? (
                  <span data-testid="run-status" data-status={run.status}>
                    <StatusPill tone={RUN_TONES[run.status]} dot>
                      {RUN_LABELS[run.status]}
                      {run.status === 'running' && ` · ${Math.round(run.progress * 100)}%`}
                    </StatusPill>
                  </span>
                ) : (
                  <span className="text-sm text-[var(--color-text-secondary)]">Portfolio created. Run it over its environment to fill the trade log.</span>
                )}
                {run?.error && <span className="text-xs text-[var(--color-risk-severe)]">{run.error}</span>}
                <div className="ml-auto flex gap-2">
                  {!run && (
                    <Button icon={Play} onClick={() => void runBacktest()} loading={starting}>
                      Run backtest
                    </Button>
                  )}
                  {run?.status === 'succeeded' && (
                    <Button icon={ArrowRight} onClick={() => navigate(`/trading/replay/${created.id}`)}>
                      Open Trade Replay
                    </Button>
                  )}
                </div>
              </div>
              {runError && (
                <div className="mt-3">
                  <ErrorNotice message={runError} />
                </div>
              )}
            </Panel>
          ) : (
            <div className="flex justify-end">
              <Button icon={ArrowRight} onClick={() => void submit()} disabled={!canSubmit} loading={creating}>
                Create Portfolio
              </Button>
            </div>
          )}
        </>
      )}
    </div>
  )
}
