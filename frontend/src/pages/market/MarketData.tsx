import { LineChart } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import CandlestickChart from '../../components/charts/CandlestickChart'
import PageHeader from '../../components/layout/PageHeader'
import Panel from '../../components/layout/Panel'
import EmptyState from '../../components/status/EmptyState'
import KpiCard from '../../components/status/KpiCard'
import {
  type Candle,
  INTERVALS,
  type Interval,
  type MarketInstrument,
  type SeriesMetrics,
  getCandles,
  getMetrics,
  listInstruments,
} from '../../services/api/market'
import { errorMessage } from '../auth/authShared'

// How far back an empty "from" reaches, so a first look is a readable chart and not ten years
const DEFAULT_LOOKBACK_DAYS: Record<Interval, number> = { daily: 180, weekly: 730, monthly: 1825, yearly: 3650 }

const FIELD_CLASS =
  'rounded border border-[var(--color-border-strong)] bg-[var(--color-bg-2)] px-3 py-1.5 text-sm text-[var(--color-text-primary)] focus:border-[var(--color-accent-strong)] focus:outline-none'

function isoDaysAgo(days: number): string {
  const date = new Date()
  date.setUTCDate(date.getUTCDate() - days)
  return date.toISOString().slice(0, 10)
}

function percent(value: string | null): string {
  return value === null ? '—' : `${(Number(value) * 100).toFixed(2)}%`
}

function tone(value: string | null): 'positive' | 'negative' | 'neutral' {
  if (value === null || Number(value) === 0) return 'neutral'
  return Number(value) > 0 ? 'positive' : 'negative'
}

function Problem({ children }: { children: string }) {
  return (
    <p role="alert" className="text-sm text-[var(--color-risk-severe)]">
      {children}
    </p>
  )
}

// The answer to one query; `key` names the query so a stale answer is never shown for a new one
type Result =
  | { key: string; ok: true; candles: Candle[]; metrics: SeriesMetrics }
  | { key: string; ok: false; error: string }

export default function MarketData() {
  const [instruments, setInstruments] = useState<MarketInstrument[] | null>(null)
  const [instrumentsError, setInstrumentsError] = useState<string | null>(null)
  const [symbol, setSymbol] = useState<string | null>(null)
  const [interval, setInterval] = useState<Interval>('daily')
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [result, setResult] = useState<Result | null>(null)

  useEffect(() => {
    let cancelled = false
    listInstruments('active')
      .then((rows) => {
        if (cancelled) return
        setInstruments(rows)
        setSymbol((current) => current ?? rows[0]?.symbol ?? null)
      })
      .catch((failure: unknown) => !cancelled && setInstrumentsError(errorMessage(failure)))
    return () => {
      cancelled = true
    }
  }, [])

  const instrument = instruments?.find((i) => i.symbol === symbol) ?? null
  const effectiveFrom = from || isoDaysAgo(DEFAULT_LOOKBACK_DAYS[interval])
  const rangeError = to && effectiveFrom > to ? 'The start date must not be after the end date.' : null

  const key = `${instrument?.id}|${interval}|${effectiveFrom}|${to}`

  useEffect(() => {
    if (!instrument || rangeError) return
    let cancelled = false
    const query = { interval, from: effectiveFrom, ...(to ? { to } : {}) }
    Promise.all([getCandles(instrument.id, query), getMetrics(instrument.id, query)])
      .then(([candles, metrics]) => !cancelled && setResult({ key, ok: true, candles, metrics }))
      .catch((failure: unknown) => !cancelled && setResult({ key, ok: false, error: errorMessage(failure) }))
    return () => {
      cancelled = true
    }
  }, [instrument, interval, effectiveFrom, to, rangeError, key])

  const current = result?.key === key ? result : null
  const loaded = current?.ok ? current : null
  const seriesError = current && !current.ok ? current.error : null

  const metrics = loaded?.metrics
  const reason = (name: string) => metrics?.unavailable[name]
  const subtitle = useMemo(() => {
    const label = INTERVALS.find((i) => i.value === interval)?.label ?? interval
    return `${label} · ${effectiveFrom} to ${to || 'latest'}`
  }, [interval, effectiveFrom, to])

  let body
  if (instrumentsError) {
    body = <Problem>{instrumentsError}</Problem>
  } else if (instruments === null) {
    body = <p className="text-sm text-[var(--color-text-muted)]">Loading instruments…</p>
  } else if (instruments.length === 0) {
    body = (
      <EmptyState
        icon={LineChart}
        title="No instruments yet"
        description="An administrator adds instruments and runs an ingestion before data appears here."
      />
    )
  } else if (rangeError) {
    body = <Problem>{rangeError}</Problem>
  } else if (seriesError) {
    body = <Problem>{seriesError}</Problem>
  } else if (!current) {
    body = <p className="text-sm text-[var(--color-text-muted)]">Loading series…</p>
  } else if (loaded && loaded.candles.length === 0) {
    body = (
      <EmptyState
        icon={LineChart}
        title="No observations in this range"
        description="Choose a different date range, or ingest this instrument's history."
      />
    )
  } else if (loaded) {
    body = <CandlestickChart candles={loaded.candles} />
  }

  return (
    <div className="qs-fade-in flex flex-col gap-6">
      <PageHeader
        title="Market Data"
        description="Daily, weekly, monthly and yearly OHLC series for instruments within the active market environment."
      />
      {instruments && instruments.length > 0 && (
        <>
          <div className="flex flex-wrap gap-2">
            {instruments.map((i) => (
              <button
                key={i.id}
                onClick={() => setSymbol(i.symbol)}
                aria-pressed={symbol === i.symbol}
                className={`mono rounded border px-3 py-1.5 text-xs font-semibold ${
                  symbol === i.symbol
                    ? 'border-[var(--color-accent-strong)] bg-[var(--color-accent)]/12 text-[var(--color-accent-strong)]'
                    : 'border-[var(--color-border-strong)] text-[var(--color-text-secondary)] hover:border-[var(--color-border-strong)]/80'
                }`}
              >
                {i.symbol}
              </button>
            ))}
          </div>
          <div className="flex flex-wrap items-end gap-4">
            <label className="flex flex-col gap-1 text-xs text-[var(--color-text-muted)]">
              Interval
              <select
                className={FIELD_CLASS}
                value={interval}
                onChange={(event) => setInterval(event.target.value as Interval)}
              >
                {INTERVALS.map((i) => (
                  <option key={i.value} value={i.value}>
                    {i.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1 text-xs text-[var(--color-text-muted)]">
              From
              <input
                className={FIELD_CLASS}
                type="date"
                value={from}
                onChange={(event) => setFrom(event.target.value)}
              />
            </label>
            <label className="flex flex-col gap-1 text-xs text-[var(--color-text-muted)]">
              To
              <input className={FIELD_CLASS} type="date" value={to} onChange={(event) => setTo(event.target.value)} />
            </label>
          </div>
        </>
      )}
      {instrument && (
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          <KpiCard
            label="Period return"
            value={percent(metrics?.periodReturn ?? null)}
            valueTone={tone(metrics?.periodReturn ?? null)}
            hint={reason('period_return')}
          />
          <KpiCard
            label="Volatility"
            value={percent(metrics?.annualisedVolatility ?? null)}
            hint={reason('annualised_volatility') ?? 'annualised'}
          />
          <KpiCard
            label="Max drawdown"
            value={percent(metrics?.maxDrawdown ?? null)}
            valueTone={tone(metrics?.maxDrawdown ?? null)}
            hint={reason('max_drawdown')}
          />
          <KpiCard
            label="Observations"
            value={metrics ? String(metrics.observations) : '—'}
            hint={metrics ? (metrics.priceBasis === 'adjusted_close' ? 'adjusted close' : 'close') : undefined}
          />
        </div>
      )}
      <Panel title={instrument ? `${instrument.name} (${instrument.symbol})` : 'Market Data'} subtitle={subtitle}>
        {body}
      </Panel>
    </div>
  )
}
