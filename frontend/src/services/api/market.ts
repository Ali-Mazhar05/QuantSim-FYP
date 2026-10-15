// Market data service calls: the instrument list, display-interval candles and chart
// metrics. Every price is a decimal string on the wire; the chart converts to numbers only
// to draw.

import { apiRequest } from './client'

const BASE = '/api/market'

export type Interval = 'daily' | 'weekly' | 'monthly' | 'yearly'

export const INTERVALS: { value: Interval; label: string }[] = [
  { value: 'daily', label: 'Daily' },
  { value: 'weekly', label: 'Weekly' },
  { value: 'monthly', label: 'Monthly' },
  { value: 'yearly', label: 'Yearly' },
]

export interface MarketInstrument {
  id: string
  symbol: string
  name: string
  sector: string
  /** Latest clean close, or null with fewer than one clean bar. */
  price: string | null
  /** Percent change from the previous clean close, or null with fewer than two bars. */
  changePct: string | null
  status: 'active' | 'retired'
  exchange: string
  assetClass: 'equity' | 'etf'
}

export interface Candle {
  /** Last session of the period: the day its close is struck. */
  date: string
  periodStart: string
  open: number
  high: number
  low: number
  close: number
  volume: number
  sessions: number
}

export interface SeriesMetrics {
  interval: Interval
  observations: number
  priceBasis: 'adjusted_close' | 'close'
  periodReturn: string | null
  annualisedVolatility: string | null
  maxDrawdown: string | null
  drawdownPeak: string | null
  drawdownTrough: string | null
  /** Metric name -> why it has no value. */
  unavailable: Record<string, string>
}

export interface SeriesQuery {
  interval: Interval
  /** First session, inclusive. */
  from?: string
  /** Last session, inclusive. */
  to?: string
}

interface ApiInstrument {
  id: string
  symbol: string
  name: string
  sector: string
  price: string | null
  change_pct: string | null
  status: 'active' | 'retired'
  exchange: string
  asset_class: 'equity' | 'etf'
}

interface ApiCandle {
  session_date: string
  period_start: string
  open: string
  high: string
  low: string
  close: string
  volume: string
  sessions: number
}

interface ApiMetrics {
  interval: Interval
  observations: number
  price_basis: 'adjusted_close' | 'close'
  period_return: string | null
  annualised_volatility: string | null
  max_drawdown: string | null
  drawdown_peak: string | null
  drawdown_trough: string | null
  unavailable: Record<string, string>
}

function query(params: SeriesQuery): string {
  const search = new URLSearchParams({ interval: params.interval })
  if (params.from) search.set('from', params.from)
  if (params.to) search.set('to', params.to)
  return search.toString()
}

export async function listInstruments(status: 'active' | 'retired' | null = 'active'): Promise<MarketInstrument[]> {
  const suffix = status ? `?status=${status}` : ''
  const rows = await apiRequest<ApiInstrument[]>(`${BASE}/instruments${suffix}`)
  return rows.map((row) => ({
    id: row.id,
    symbol: row.symbol,
    name: row.name,
    sector: row.sector,
    price: row.price,
    changePct: row.change_pct,
    status: row.status,
    exchange: row.exchange,
    assetClass: row.asset_class,
  }))
}

export async function getCandles(instrumentId: string, params: SeriesQuery): Promise<Candle[]> {
  const body = await apiRequest<{ items: ApiCandle[] }>(`${BASE}/instruments/${instrumentId}/candles?${query(params)}`)
  return body.items.map((c) => ({
    date: c.session_date,
    periodStart: c.period_start,
    open: Number(c.open),
    high: Number(c.high),
    low: Number(c.low),
    close: Number(c.close),
    volume: Number(c.volume),
    sessions: c.sessions,
  }))
}

export async function getMetrics(instrumentId: string, params: SeriesQuery): Promise<SeriesMetrics> {
  const m = await apiRequest<ApiMetrics>(`${BASE}/instruments/${instrumentId}/metrics?${query(params)}`)
  return {
    interval: m.interval,
    observations: m.observations,
    priceBasis: m.price_basis,
    periodReturn: m.period_return,
    annualisedVolatility: m.annualised_volatility,
    maxDrawdown: m.max_drawdown,
    drawdownPeak: m.drawdown_peak,
    drawdownTrough: m.drawdown_trough,
    unavailable: m.unavailable,
  }
}
