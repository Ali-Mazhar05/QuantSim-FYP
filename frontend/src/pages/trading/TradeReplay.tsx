import clsx from 'clsx'
import { ArrowRight, Pause, Play } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import Button from '../../components/forms/Button'
import Panel from '../../components/layout/Panel'
import PageHeader from '../../components/layout/PageHeader'
import DataTable, { type Column } from '../../components/tables/DataTable'
import EmptyState from '../../components/status/EmptyState'
import StatusPill from '../../components/status/StatusPill'
import { useDemoStore } from '../../demo/demoState'
import { ApiError } from '../../services/api/client'
import {
  type Portfolio,
  type TradeLogEvent,
  type ValuePoint,
  BASE_STEP_MS,
  EVENT_PAGE,
  SPEEDS,
  formatUsd,
  getPortfolio,
  getValueSeries,
  isId,
  listEvents,
  listPortfolios,
} from './tradingApi'
import { type Failure, failureOf } from './tradingFormat'
import { FailureState, Loading } from './tradingShared'

/** Rows the table keeps: the most recent events played. */
const SHOWN_ROWS = 250

type Tone = 'neutral' | 'success' | 'warning' | 'danger' | 'info'

const STATUS: Record<string, { label: string; tone: Tone }> = {
  RUN_STARTED: { label: 'Started', tone: 'info' },
  TICK: { label: 'Market tick', tone: 'neutral' },
  ORDER_PLACED: { label: 'Placed', tone: 'info' },
  ORDER_FILLED: { label: 'Filled', tone: 'success' },
  ORDER_REJECTED: { label: 'Rejected', tone: 'danger' },
  ORDER_EXPIRED: { label: 'Expired', tone: 'warning' },
  VALUED: { label: 'Valued', tone: 'neutral' },
  RUN_COMPLETED: { label: 'Completed', tone: 'success' },
}

const text = (payload: Record<string, unknown>, key: string): string | null => {
  const value = payload[key]
  return value === null || value === undefined ? null : String(value)
}

const columns: Column<TradeLogEvent>[] = [
  { key: 'time', header: 'Time', render: (r) => <span className="mono">{r.event_time.slice(0, 10)}</span> },
  {
    key: 'event',
    header: 'Event',
    render: (r) => {
      const side = text(r.payload, 'side')
      return (
        <span
          className={clsx(
            'mono font-semibold',
            side === 'buy' && 'text-[var(--color-risk-low)]',
            side === 'sell' && 'text-[var(--color-risk-severe)]',
          )}
        >
          {r.type}
          {side && ` ${side.toUpperCase()}`}
        </span>
      )
    },
  },
  { key: 'instrument', header: 'Instrument', render: (r) => <span className="mono">{text(r.payload, 'symbol') ?? '—'}</span> },
  { key: 'quantity', header: 'Quantity', align: 'right', render: (r) => <span className="mono">{text(r.payload, 'quantity') ?? '—'}</span> },
  {
    key: 'price',
    header: 'Price',
    align: 'right',
    render: (r) => {
      const price = text(r.payload, 'fill_price') ?? text(r.payload, 'limit_price')
      return <span className="mono">{price === null ? '—' : formatUsd(price, 2)}</span>
    },
  },
  {
    key: 'status',
    header: 'Status',
    render: (r) => {
      const status = STATUS[r.type] ?? { label: r.type, tone: 'neutral' as Tone }
      const detail =
        r.type === 'ORDER_FILLED'
          ? ` · cost ${formatUsd(text(r.payload, 'cost_total'), 2)} · slippage ${formatUsd(text(r.payload, 'slippage'), 4)}`
          : r.type === 'VALUED'
            ? ` ${formatUsd(text(r.payload, 'portfolio_value'))}`
            : r.type === 'ORDER_REJECTED'
              ? ` · ${text(r.payload, 'reason') ?? ''}`
              : ''
      return (
        <StatusPill tone={status.tone}>
          {status.label}
          {detail}
        </StatusPill>
      )
    },
  },
]

const TIMELINE = ['Market Tick', 'Strategy Signal', 'Order Placed', 'Order Filled', 'Portfolio Updated']
const TIMELINE_STEP: Record<string, number> = {
  TICK: 0,
  RUN_STARTED: 1,
  ORDER_PLACED: 2,
  ORDER_REJECTED: 2,
  ORDER_EXPIRED: 2,
  ORDER_FILLED: 3,
  VALUED: 4,
  RUN_COMPLETED: 4,
}

export default function TradeReplay() {
  const { id = '' } = useParams()
  // A new id starts a fresh replay: nothing of the previous run's state carries over
  return <Replay key={id} id={id} />
}

function Replay({ id }: { id: string }) {
  const navigate = useNavigate()
  const advanceTo = useDemoStore((s) => s.advanceTo)
  const known = isId(id)

  const [runs, setRuns] = useState<Portfolio[] | null>(null)
  const [portfolio, setPortfolio] = useState<Portfolio | null>(null)
  const [missing, setMissing] = useState(false)
  const [failure, setFailure] = useState<Failure | null>(null)
  const [events, setEvents] = useState<TradeLogEvent[] | null>(null)
  const [allLoaded, setAllLoaded] = useState(false)
  const [values, setValues] = useState<ValuePoint[]>([])

  // Wants to play; it stops by itself at the end of the log (see isPlaying)
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState(5)
  const [position, setPosition] = useState(0)

  // The portfolios that have a trade log, for the run picker
  useEffect(() => {
    let cancelled = false
    listPortfolios()
      .then((rows) => !cancelled && setRuns(rows.filter((p) => p.source_fingerprint !== null || p.id === id)))
      .catch(() => !cancelled && setRuns([]))
    return () => {
      cancelled = true
    }
  }, [id])

  // The chosen portfolio, its value series and its log, paged in by seq
  useEffect(() => {
    if (!known) return
    let cancelled = false
    const load = async () => {
      const found = await getPortfolio(id)
      if (cancelled) return
      setPortfolio(found)
      getValueSeries(id)
        .then((series) => !cancelled && setValues(series))
        .catch(() => undefined)
      let after = 0
      for (;;) {
        const page = await listEvents(id, after, EVENT_PAGE)
        if (cancelled) return
        setEvents((current) => [...(current ?? []), ...page.items])
        if (page.next_cursor === null) break
        after = page.next_cursor
      }
      setAllLoaded(true)
    }
    load().catch((error: unknown) => {
      if (cancelled) return
      if (error instanceof ApiError && error.status === 404) setMissing(true)
      else setFailure(failureOf(error))
    })
    return () => {
      cancelled = true
    }
  }, [id, known])

  const total = events?.length ?? 0
  const complete = allLoaded && total > 0 && position >= total
  const isPlaying = playing && !complete

  useEffect(() => {
    if (!isPlaying || position >= total) return
    const timer = window.setTimeout(() => setPosition((p) => Math.min(total, p + 1)), BASE_STEP_MS / speed)
    return () => window.clearTimeout(timer)
  }, [isPlaying, speed, position, total])

  useEffect(() => {
    if (complete) advanceTo('TRADING_COMPLETE')
  }, [complete, advanceTo])

  const played = useMemo(() => (events ?? []).slice(0, position), [events, position])
  const current = played[played.length - 1]
  const currentSeq = current?.seq ?? 0
  const value = useMemo(() => {
    let found: ValuePoint | null = null
    for (const point of values) if (point.seq <= currentSeq) found = point
    return found
  }, [values, currentSeq])
  const fills = played.filter((e) => e.type === 'ORDER_FILLED').length
  const orders = (events ?? []).filter((e) => e.type === 'ORDER_PLACED').length
  const sessionEvent = [...played].reverse().find((e) => e.type === 'TICK')
  const sessions = (events ?? []).filter((e) => e.type === 'TICK').length

  const initial = portfolio ? Number(portfolio.initial_capital) : 0
  const shownValue = value?.value ?? portfolio?.initial_capital ?? null
  const changePct = initial > 0 && shownValue ? ((Number(shownValue) - initial) / initial) * 100 : 0

  const title = portfolio ? `Trade Replay — ${portfolio.name}` : `Trade Replay — Simulation #${id}`
  const status = complete ? 'Complete' : isPlaying ? 'Running' : position === 0 ? 'Ready' : 'Paused'
  const step = current ? TIMELINE_STEP[current.type] : undefined

  const picker = (
    <select
      aria-label="Run"
      value={known ? id : ''}
      onChange={(e) => e.target.value && navigate(`/trading/replay/${e.target.value}`)}
      className="rounded border border-[var(--color-border-strong)] bg-[var(--color-bg-2)] px-2.5 py-1 text-xs text-[var(--color-text-primary)]"
      data-testid="replay-run"
    >
      <option value="">{runs === null ? 'Loading runs…' : runs.length === 0 ? 'No portfolio has run yet' : 'Choose a run…'}</option>
      {(runs ?? []).map((p) => (
        <option key={p.id} value={p.id}>
          {p.name} — {p.strategy_name}
        </option>
      ))}
    </select>
  )

  return (
    <div className="qs-fade-in flex flex-col gap-6">
      <PageHeader
        eyebrow="Step 6 of 8 — Trading"
        title={title}
        description={
          portfolio
            ? `${portfolio.strategy_name} execution inside the portfolio's market environment.`
            : "Pick a portfolio's run to replay its trade log."
        }
        breadcrumbs={[{ label: 'Trade Replay' }]}
        action={
          <span data-testid="replay-status" data-status={status}>
            <StatusPill tone={complete ? 'success' : isPlaying ? 'info' : 'neutral'} dot>
              {status}
            </StatusPill>
          </span>
        }
      />

      <Panel>
        <div className="flex flex-wrap items-center gap-4">
          {picker}
          <Button
            variant="secondary"
            size="sm"
            icon={isPlaying ? Pause : Play}
            onClick={() => {
              // Play at the end starts the log again
              if (complete) setPosition(0)
              setPlaying(!isPlaying)
            }}
            disabled={total === 0}
            data-testid="replay-play"
          >
            {isPlaying ? 'Pause' : 'Play'}
          </Button>
          <div className="flex gap-1">
            {SPEEDS.map((s) => (
              <button
                key={s}
                onClick={() => setSpeed(s)}
                aria-pressed={speed === s}
                data-testid={`replay-speed-${s}`}
                className={clsx(
                  'rounded border px-2.5 py-1 text-xs font-semibold',
                  speed === s
                    ? 'border-[var(--color-accent-strong)] bg-[var(--color-accent)]/12 text-[var(--color-accent-strong)]'
                    : 'border-[var(--color-border-strong)] text-[var(--color-text-secondary)]',
                )}
              >
                {s}x
              </button>
            ))}
          </div>
          <label className="flex items-center gap-2 text-xs text-[var(--color-text-muted)]">
            <input
              type="range"
              aria-label="Seek"
              min={0}
              max={total}
              value={position}
              onChange={(e) => setPosition(Number(e.target.value))}
              disabled={total === 0}
              className="w-40 accent-[var(--color-accent)]"
              data-testid="replay-seek"
            />
            <span className="mono" data-testid="replay-position">
              {position} / {total}
              {!allLoaded && total > 0 ? '+' : ''}
            </span>
          </label>
          <div className="ml-auto flex items-center gap-2 overflow-x-auto">
            {TIMELINE.map((t, i) => (
              <span
                key={t}
                className={clsx(
                  'whitespace-nowrap rounded px-2 py-1 text-[11px] font-medium',
                  i === step ? 'bg-[var(--color-accent)]/15 text-[var(--color-accent-strong)]' : 'text-[var(--color-text-muted)]',
                )}
              >
                {t}
                {i < TIMELINE.length - 1 && ' →'}
              </span>
            ))}
          </div>
        </div>
      </Panel>

      {!known || missing ? (
        <EmptyState
          title={missing ? 'No portfolio has this id' : 'Choose a run to replay'}
          description="Pick a portfolio that has run from the list above, or start a backtest from Create Portfolio."
        />
      ) : failure ? (
        <FailureState failure={failure} />
      ) : events === null ? (
        <Loading what="the trade log" />
      ) : total === 0 ? (
        <EmptyState title="This portfolio has not run yet" description="Run a backtest from Create Portfolio; its trade log is replayed here." />
      ) : (
        <>
          <div className="grid grid-cols-1 gap-5 md:grid-cols-3">
            <Panel title="Portfolio Value">
              <div className="mono text-2xl font-semibold text-[var(--color-text-primary)]" data-testid="replay-value">
                {formatUsd(shownValue)}
              </div>
              <div className={clsx('mt-1 text-xs', changePct >= 0 ? 'text-[var(--color-risk-low)]' : 'text-[var(--color-risk-severe)]')}>
                {changePct >= 0 ? '+' : ''}
                {changePct.toFixed(2)}% since open
              </div>
            </Panel>
            <Panel title="Fills">
              <div className="mono text-2xl font-semibold text-[var(--color-text-primary)]" data-testid="replay-fills">
                {fills}
              </div>
              <div className="mt-1 text-xs text-[var(--color-text-muted)]">of {orders} orders</div>
            </Panel>
            <Panel title="Session Time">
              <div className="mono text-2xl font-semibold text-[var(--color-text-primary)]">
                {sessionEvent ? `Session ${Number(sessionEvent.payload.session) + 1}` : '—'}
                <span className="text-base text-[var(--color-text-muted)]"> / {sessions}</span>
              </div>
              <div className="mt-1 text-xs text-[var(--color-text-muted)]">
                {sessionEvent ? String(sessionEvent.payload.ts ?? sessionEvent.event_time).slice(0, 10) : 'Before the first session'}
              </div>
            </Panel>
          </div>

          <Panel title="Order Events" bodyClassName="p-0">
            <div data-testid="replay-events">
              <DataTable columns={columns} rows={played.slice(-SHOWN_ROWS)} rowKey={(r) => String(r.seq)} />
            </div>
          </Panel>

          {complete && (
            <div className="flex justify-end">
              <Button icon={ArrowRight} onClick={() => navigate('/risk/overview')}>
                Analyze Portfolio Risk
              </Button>
            </div>
          )}
        </>
      )}
    </div>
  )
}
