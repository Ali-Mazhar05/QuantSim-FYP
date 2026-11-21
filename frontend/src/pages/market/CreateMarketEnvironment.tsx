import clsx from 'clsx'
import { ArrowRight } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import CandlestickChart from '../../components/charts/CandlestickChart'
import Button from '../../components/forms/Button'
import Panel from '../../components/layout/Panel'
import PageHeader from '../../components/layout/PageHeader'
import EmptyState from '../../components/status/EmptyState'
import { useDemoStore } from '../../demo/demoState'
import { useNotifications } from '../../demo/notifications'
import { useCreateEnvironment } from '../../hooks/useCreateEnvironment'
import { type Candle, type MarketInstrument, getCandles, listInstruments } from '../../services/api/market'
import type { MarketEnvironment } from '../../types'
import { errorMessage } from '../auth/authShared'

// The prototype's data window, basket and starting selection: what the page shows is what
// is saved
const UNIVERSE = 'US Technology Basket'
const START = '2025-01-01'
const END = '2026-06-30'
const DEFAULT_SELECTION = ['AAPL', 'MSFT', 'NVDA', 'AMZN', 'GOOGL']

type Preview = { symbol: string; candles: Candle[] } | { symbol: string; error: string }

export default function CreateMarketEnvironment() {
  const navigate = useNavigate()
  const advanceTo = useDemoStore((s) => s.advanceTo)
  const setActiveEnvironment = useDemoStore((s) => s.setActiveEnvironment)
  const push = useNotifications((s) => s.push)
  const { mutateAsync: createEnvironment } = useCreateEnvironment()
  const [type, setType] = useState<MarketEnvironment['type']>('Synthetic Market')
  const [instruments, setInstruments] = useState<MarketInstrument[] | null>(null)
  const [failure, setFailure] = useState<string | null>(null)
  const [selected, setSelected] = useState<string[]>([])
  const [preview, setPreview] = useState<Preview | null>(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    let cancelled = false
    listInstruments('active')
      .then((rows) => {
        if (cancelled) return
        setInstruments(rows)
        const known = new Set(rows.map((r) => r.symbol))
        setSelected(DEFAULT_SELECTION.filter((s) => known.has(s)))
      })
      .catch((error: unknown) => !cancelled && setFailure(errorMessage(error)))
    return () => {
      cancelled = true
    }
  }, [])

  const toggle = (sym: string) => {
    setSelected((s) => (s.includes(sym) ? s.filter((x) => x !== sym) : [...s, sym]))
  }

  // The preview is the first selected instrument's series over the data window
  const reference = instruments?.find((i) => i.symbol === selected[0])
  const referenceId = reference?.id
  const referenceSymbol = reference?.symbol
  useEffect(() => {
    if (!referenceId || !referenceSymbol) return
    let cancelled = false
    getCandles(referenceId, START, END)
      .then((candles) => !cancelled && setPreview({ symbol: referenceSymbol, candles }))
      .catch((error: unknown) => !cancelled && setPreview({ symbol: referenceSymbol, error: errorMessage(error) }))
    return () => {
      cancelled = true
    }
  }, [referenceId, referenceSymbol])

  const shown = preview && preview.symbol === referenceSymbol ? preview : null
  let chart
  if (!reference) {
    chart = <EmptyState title="No instrument selected" description="Select at least one instrument for the universe." />
  } else if (!shown) {
    chart = <p className="text-sm text-[var(--color-text-muted)]">Loading…</p>
  } else if ('error' in shown) {
    chart = <p role="alert" className="text-sm text-[var(--color-risk-severe)]">{shown.error}</p>
  } else if (shown.candles.length === 0) {
    chart = <EmptyState title="No observations in this window" description={`${shown.symbol} has no ingested sessions between ${START} and ${END}.`} />
  } else {
    chart = <CandlestickChart candles={shown.candles} height={180} />
  }

  const create = async () => {
    const ids = (instruments ?? []).filter((i) => selected.includes(i.symbol)).map((i) => i.id)
    setSaving(true)
    try {
      const environment = await createEnvironment({
        name: UNIVERSE,
        type,
        universe: UNIVERSE,
        instrumentIds: ids,
        start: START,
        end: END,
        frequency: 'Daily',
      })
      setActiveEnvironment(environment.id)
      advanceTo('MARKET_SELECTED')
      navigate('/simulation/configure')
    } catch (error) {
      push(errorMessage(error), 'warning')
      setSaving(false)
    }
  }

  return (
    <div className="qs-fade-in flex flex-col gap-6">
      <PageHeader
        eyebrow="Step 1 of 8 — Market"
        title="Create Market Environment"
        description="Choose a historical replay or a synthetic market to run your simulation inside."
        breadcrumbs={[{ label: 'Market Environments', to: '/market/environments' }, { label: 'New' }]}
      />

      <Panel title="Market Type">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {(['Historical Replay', 'Synthetic Market'] as const).map((t) => (
            <button
              key={t}
              onClick={() => setType(t)}
              className={clsx(
                'rounded border p-4 text-left transition-colors',
                type === t ? 'border-[var(--color-accent-strong)] bg-[var(--color-accent)]/8' : 'border-[var(--color-border-strong)] hover:border-[var(--color-border-strong)]/80',
              )}
            >
              <div className={clsx('text-sm font-semibold', type === t ? 'text-[var(--color-accent-strong)]' : 'text-[var(--color-text-primary)]')}>{t}</div>
              <div className="mt-1 text-xs text-[var(--color-text-muted)]">
                {t === 'Historical Replay'
                  ? 'Replay recorded market data over a fixed historical window.'
                  : 'Generate a synthetic market calibrated to historical statistics.'}
              </div>
            </button>
          ))}
        </div>
      </Panel>

      <Panel title="Universe" subtitle={UNIVERSE}>
        {failure ? (
          <p role="alert" className="text-sm text-[var(--color-risk-severe)]">{failure}</p>
        ) : instruments === null ? (
          <p className="text-sm text-[var(--color-text-muted)]">Loading instruments…</p>
        ) : instruments.length === 0 ? (
          <EmptyState title="No instruments yet" description="An administrator adds instruments through the market API." />
        ) : (
          <div className="flex flex-wrap gap-2">
            {instruments.map((inst) => (
              <button
                key={inst.symbol}
                onClick={() => toggle(inst.symbol)}
                className={clsx(
                  'mono rounded border px-3 py-1.5 text-xs font-semibold transition-colors',
                  selected.includes(inst.symbol)
                    ? 'border-[var(--color-accent-strong)] bg-[var(--color-accent)]/12 text-[var(--color-accent-strong)]'
                    : 'border-[var(--color-border-strong)] text-[var(--color-text-secondary)] hover:border-[var(--color-border-strong)]/80',
                )}
              >
                {inst.symbol}
              </button>
            ))}
          </div>
        )}
      </Panel>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        <Panel title="Data Window">
          <dl className="grid grid-cols-2 gap-3 text-sm">
            <div>
              <dt className="text-xs text-[var(--color-text-muted)]">Start</dt>
              <dd className="mono mt-0.5 text-[var(--color-text-primary)]">{START}</dd>
            </div>
            <div>
              <dt className="text-xs text-[var(--color-text-muted)]">End</dt>
              <dd className="mono mt-0.5 text-[var(--color-text-primary)]">{END}</dd>
            </div>
            <div>
              <dt className="text-xs text-[var(--color-text-muted)]">Frequency</dt>
              <dd className="mt-0.5 text-[var(--color-text-primary)]">Daily</dd>
            </div>
            <div>
              <dt className="text-xs text-[var(--color-text-muted)]">Universe</dt>
              <dd className="mt-0.5 text-[var(--color-text-primary)]">{UNIVERSE}</dd>
            </div>
          </dl>
        </Panel>
        <Panel title="Preview" subtitle={`${referenceSymbol ?? '—'} — reference series`}>
          {chart}
        </Panel>
      </div>

      <div className="flex justify-end">
        <Button icon={ArrowRight} disabled={saving || selected.length === 0} onClick={() => void create()}>
          Continue to Simulation
        </Button>
      </div>
    </div>
  )
}
