import clsx from 'clsx'
import { ArrowRight, Pause, Play } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import Button from '../../components/forms/Button'
import Panel from '../../components/layout/Panel'
import PageHeader from '../../components/layout/PageHeader'
import DataTable, { type Column } from '../../components/tables/DataTable'
import StatusPill from '../../components/status/StatusPill'
import { useDemoStore } from '../../demo/demoState'
import { TRADE_EVENTS } from '../../services/mock/data'
import type { TradeEvent } from '../../types'

const SPEEDS = [1, 5, 20]

const columns: Column<TradeEvent>[] = [
  { key: 'time', header: 'Time', render: (r) => <span className="mono">{r.time}</span> },
  {
    key: 'event',
    header: 'Event',
    render: (r) => (
      <span className={clsx('mono font-semibold', r.event === 'BUY' ? 'text-[var(--color-risk-low)]' : 'text-[var(--color-risk-severe)]')}>
        {r.event}
      </span>
    ),
  },
  { key: 'instrument', header: 'Instrument', render: (r) => <span className="mono">{r.instrument}</span> },
  { key: 'quantity', header: 'Quantity', align: 'right', render: (r) => <span className="mono">{r.quantity}</span> },
  { key: 'price', header: 'Price', align: 'right', render: (r) => <span className="mono">${r.price.toFixed(2)}</span> },
  { key: 'status', header: 'Status', render: (r) => <StatusPill tone="success">{r.status}</StatusPill> },
]

const TIMELINE = ['Market Tick', 'Strategy Signal', 'Order Placed', 'Order Filled', 'Portfolio Updated']

export default function TradeReplay() {
  const { id = '1042' } = useParams()
  const navigate = useNavigate()
  const advanceTo = useDemoStore((s) => s.advanceTo)
  const hasReached = useDemoStore((s) => s.hasReached)

  const [playing, setPlaying] = useState(!hasReached('TRADING_COMPLETE'))
  const [speed, setSpeed] = useState(5)
  const [count, setCount] = useState(hasReached('TRADING_COMPLETE') ? TRADE_EVENTS.length : 0)
  const [tick, setTick] = useState(0)

  useEffect(() => {
    if (!playing || count >= TRADE_EVENTS.length) return
    const interval = setInterval(() => {
      setCount((c) => Math.min(TRADE_EVENTS.length, c + 1))
      setTick((t) => t + 1)
    }, 700 / speed)
    return () => clearInterval(interval)
  }, [playing, speed, count])

  useEffect(() => {
    if (count >= TRADE_EVENTS.length) {
      setPlaying(false)
      advanceTo('TRADING_COMPLETE')
    }
  }, [count, advanceTo])

  const value = 1_000_000 + count * 8342
  const events = TRADE_EVENTS.slice(0, count)
  const complete = count >= TRADE_EVENTS.length

  return (
    <div className="qs-fade-in flex flex-col gap-6">
      <PageHeader
        eyebrow="Step 6 of 8 — Trading"
        title={`Trade Replay — Simulation #${id}`}
        description="Momentum Strategy execution inside the simulated market."
        breadcrumbs={[{ label: 'Trade Replay' }]}
        action={<StatusPill tone={complete ? 'success' : 'info'} dot>{complete ? 'Complete' : 'Running'}</StatusPill>}
      />

      <Panel>
        <div className="flex flex-wrap items-center gap-4">
          <Button variant="secondary" size="sm" icon={playing ? Pause : Play} onClick={() => setPlaying((v) => !v)} disabled={complete}>
            {playing ? 'Pause' : 'Play'}
          </Button>
          <div className="flex gap-1">
            {SPEEDS.map((s) => (
              <button
                key={s}
                onClick={() => setSpeed(s)}
                className={clsx(
                  'rounded border px-2.5 py-1 text-xs font-semibold',
                  speed === s
                    ? 'border-[var(--color-accent)] bg-[var(--color-accent)]/12 text-[var(--color-accent-strong)]'
                    : 'border-[var(--color-border-strong)] text-[var(--color-text-secondary)]',
                )}
              >
                {s}x
              </button>
            ))}
          </div>
          <div className="ml-auto flex items-center gap-2 overflow-x-auto">
            {TIMELINE.map((t, i) => (
              <span
                key={t}
                className={clsx(
                  'whitespace-nowrap rounded px-2 py-1 text-[11px] font-medium',
                  i === tick % TIMELINE.length && playing
                    ? 'bg-[var(--color-accent)]/15 text-[var(--color-accent-strong)]'
                    : 'text-[var(--color-text-muted)]',
                )}
              >
                {t}
                {i < TIMELINE.length - 1 && ' →'}
              </span>
            ))}
          </div>
        </div>
      </Panel>

      <div className="grid grid-cols-1 gap-5 md:grid-cols-3">
        <Panel title="Portfolio Value">
          <div className="mono text-2xl font-semibold text-[var(--color-text-primary)]">${value.toLocaleString()}</div>
          <div className="mt-1 text-xs text-[var(--color-risk-low)]">
            +{(((value - 1_000_000) / 1_000_000) * 100).toFixed(2)}% since open
          </div>
        </Panel>
        <Panel title="Fills">
          <div className="mono text-2xl font-semibold text-[var(--color-text-primary)]">{count}</div>
          <div className="mt-1 text-xs text-[var(--color-text-muted)]">of {TRADE_EVENTS.length} orders</div>
        </Panel>
        <Panel title="Session Time">
          <div className="mono text-2xl font-semibold text-[var(--color-text-primary)]">09:30 – 16:00</div>
          <div className="mt-1 text-xs text-[var(--color-text-muted)]">Simulated trading day</div>
        </Panel>
      </div>

      <Panel title="Order Events" bodyClassName="p-0">
        <DataTable columns={columns} rows={events} rowKey={(r) => r.time} />
      </Panel>

      {complete && (
        <div className="flex justify-end">
          <Button icon={ArrowRight} onClick={() => navigate('/risk/overview')}>
            Analyze Portfolio Risk
          </Button>
        </div>
      )}
    </div>
  )
}
