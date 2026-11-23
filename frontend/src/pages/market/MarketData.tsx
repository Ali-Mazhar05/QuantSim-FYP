import { useState } from 'react'
import CandlestickChart from '../../components/charts/CandlestickChart'
import Button from '../../components/forms/Button'
import DateRange from '../../components/forms/DateRange'
import { isInverted } from '../../components/forms/dateWindow'
import Select from '../../components/forms/Select'
import Panel from '../../components/layout/Panel'
import PageHeader from '../../components/layout/PageHeader'
import EmptyState from '../../components/status/EmptyState'
import { classifyError } from '../../hooks/apiError'
import { isExplicit, useCandles, useMetrics } from '../../hooks/useCandles'
import { useInstruments } from '../../hooks/useInstruments'
import { DEFAULT_WINDOW, INTERVALS, type Interval } from '../../services/api/market'
import MetricCards from './MetricCards'

const intervalLabel = (interval: Interval) => INTERVALS.find((i) => i.value === interval)?.label ?? interval

export default function MarketData() {
  const instruments = useInstruments('active')
  const [symbol, setSymbol] = useState('')
  const [interval, setInterval] = useState<Interval>('daily')
  const [range, setRange] = useState({ from: '', to: '' })

  const rows = instruments.data ?? null
  const inst = rows?.find((i) => i.symbol === symbol) ?? rows?.[0]
  const choice = { interval, ...range }
  const series = useCandles(inst?.id, choice)
  const metrics = useMetrics(inst?.id, interval, series.data)

  const explicit = isExplicit(choice)
  const defaults = DEFAULT_WINDOW[interval]
  const subtitle = `${intervalLabel(interval)} · ${
    explicit ? `${range.from || 'start'} to ${range.to || 'latest'}` : `last ${defaults.buckets} ${defaults.unit}`
  }`

  let chart
  if (instruments.error) {
    chart = <p role="alert" className="text-sm text-[var(--color-risk-severe)]">{classifyError(instruments.error).message}</p>
  } else if (rows === null) {
    chart = <p className="text-sm text-[var(--color-text-muted)]">Loading…</p>
  } else if (!inst) {
    chart = (
      <EmptyState title="No instruments yet" description="Instruments appear here once an administrator adds them and data is ingested." />
    )
  } else if (isInverted(range.from, range.to)) {
    chart = <EmptyState title="Choose a valid window" description="The start date is after the end date." />
  } else if (series.error) {
    chart = <p role="alert" className="text-sm text-[var(--color-risk-severe)]">{classifyError(series.error).message}</p>
  } else if (series.data === undefined) {
    chart = <p className="text-sm text-[var(--color-text-muted)]">Loading…</p>
  } else if (series.data.length === 0) {
    chart = explicit ? (
      <EmptyState
        title="No observations in this window"
        description={`${inst.symbol} has no ingested sessions between ${range.from || 'the start'} and ${range.to || 'today'}.`}
      />
    ) : (
      <EmptyState title="No observations yet" description="This instrument has no ingested sessions." />
    )
  } else {
    chart = <CandlestickChart candles={series.data} interval={intervalLabel(interval)} />
  }

  return (
    <div className="qs-fade-in flex flex-col gap-6">
      <PageHeader title="Market Data" description="Daily OHLC series for instruments within the active market environment." />
      <div className="flex flex-wrap gap-2">
        {(rows ?? []).map((i) => (
          <button
            key={i.symbol}
            onClick={() => setSymbol(i.symbol)}
            className={`mono rounded border px-3 py-1.5 text-xs font-semibold ${
              inst?.symbol === i.symbol
                ? 'border-[var(--color-accent-strong)] bg-[var(--color-accent)]/12 text-[var(--color-accent-strong)]'
                : 'border-[var(--color-border-strong)] text-[var(--color-text-secondary)] hover:border-[var(--color-border-strong)]/80'
            }`}
          >
            {i.symbol}
          </button>
        ))}
      </div>
      <div className="flex flex-wrap items-end gap-4">
        <Select label="Interval" value={interval} options={INTERVALS} onChange={setInterval} />
        <DateRange from={range.from} to={range.to} onChange={setRange} />
        <Button variant="secondary" size="sm" disabled={!explicit} onClick={() => setRange({ from: '', to: '' })}>
          Reset window
        </Button>
      </div>
      <Panel title={inst ? `${inst.name} (${inst.symbol})` : 'Market Data'} subtitle={subtitle}>
        {chart}
      </Panel>
      {inst && series.data && series.data.length > 0 && (
        <MetricCards
          metrics={metrics.data}
          loading={metrics.isPending}
          error={metrics.error ? classifyError(metrics.error).message : null}
        />
      )}
    </div>
  )
}
