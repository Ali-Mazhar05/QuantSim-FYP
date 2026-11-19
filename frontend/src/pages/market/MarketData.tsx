import { useEffect, useState } from 'react'
import CandlestickChart from '../../components/charts/CandlestickChart'
import Panel from '../../components/layout/Panel'
import PageHeader from '../../components/layout/PageHeader'
import EmptyState from '../../components/status/EmptyState'
import { type Candle, type MarketInstrument, getRecentCandles, listInstruments } from '../../services/api/market'
import { errorMessage } from '../auth/authShared'

// The POC chart shows the last 90 sessions
const SESSIONS = 90

// The series as one answer to one instrument, so a stale answer is never drawn for another
type Series = { id: string; candles: Candle[] } | { id: string; error: string }

export default function MarketData() {
  const [instruments, setInstruments] = useState<MarketInstrument[] | null>(null)
  const [failure, setFailure] = useState<string | null>(null)
  const [symbol, setSymbol] = useState('')
  const [series, setSeries] = useState<Series | null>(null)

  useEffect(() => {
    let cancelled = false
    listInstruments('active')
      .then((rows) => {
        if (cancelled) return
        setInstruments(rows)
        setSymbol((current) => current || rows[0]?.symbol || '')
      })
      .catch((error: unknown) => !cancelled && setFailure(errorMessage(error)))
    return () => {
      cancelled = true
    }
  }, [])

  const inst = instruments?.find((i) => i.symbol === symbol)
  const id = inst?.id

  useEffect(() => {
    if (!id) return
    let cancelled = false
    getRecentCandles(id, SESSIONS)
      .then((candles) => !cancelled && setSeries({ id, candles }))
      .catch((error: unknown) => !cancelled && setSeries({ id, error: errorMessage(error) }))
    return () => {
      cancelled = true
    }
  }, [id])

  const current = series && series.id === id ? series : null

  let chart
  if (failure) {
    chart = <p role="alert" className="text-sm text-[var(--color-risk-severe)]">{failure}</p>
  } else if (instruments === null || (inst && !current)) {
    chart = <p className="text-sm text-[var(--color-text-muted)]">Loading…</p>
  } else if (!inst) {
    chart = (
      <EmptyState title="No instruments yet" description="Instruments appear here once an administrator adds them and data is ingested." />
    )
  } else if (current && 'error' in current) {
    chart = <p role="alert" className="text-sm text-[var(--color-risk-severe)]">{current.error}</p>
  } else if (current && current.candles.length === 0) {
    chart = <EmptyState title="No observations yet" description="This instrument has no ingested sessions." />
  } else if (current) {
    chart = <CandlestickChart candles={current.candles} />
  }

  return (
    <div className="qs-fade-in flex flex-col gap-6">
      <PageHeader title="Market Data" description="Daily OHLC series for instruments within the active market environment." />
      <div className="flex flex-wrap gap-2">
        {(instruments ?? []).map((i) => (
          <button
            key={i.symbol}
            onClick={() => setSymbol(i.symbol)}
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
      <Panel title={inst ? `${inst.name} (${inst.symbol})` : 'Market Data'} subtitle={`Daily · last ${SESSIONS} sessions`}>
        {chart}
      </Panel>
    </div>
  )
}
