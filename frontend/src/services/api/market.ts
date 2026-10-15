// Market data service calls for the POC pages: the instrument list and the recent daily
// series. Every price is a decimal string on the wire; the chart converts to numbers only
// to draw. Interval filtering and metrics are served by the same API (candles and metrics
// routes) but the prototype has no control for them, so no page asks for them.

import { apiRequest } from './client'

const BASE = '/api/market'

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
  /** The session the candle covers. */
  date: string
  open: number
  high: number
  low: number
  close: number
  volume: number
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
  open: string
  high: string
  low: string
  close: string
  volume: string
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

/** The last `sessions` daily candles of an instrument, oldest first: the latest available
 * ingested data, however old. The API takes a date range, so the request first reaches back
 * far enough to hold that many sessions (weekends and holidays) and, only when that holds
 * nothing because the data is older, asks for the whole history. */
export async function getRecentCandles(instrumentId: string, sessions: number): Promise<Candle[]> {
  const path = `${BASE}/instruments/${instrumentId}/candles`
  const from = new Date()
  from.setUTCDate(from.getUTCDate() - Math.ceil(sessions * 1.6) - 10)
  const recent = new URLSearchParams({ interval: 'daily', from: from.toISOString().slice(0, 10) })
  let body = await apiRequest<{ items: ApiCandle[] }>(`${path}?${recent}`)
  if (body.items.length === 0) body = await apiRequest<{ items: ApiCandle[] }>(`${path}?interval=daily`)
  return body.items.slice(-sessions).map((c) => ({
    date: c.session_date,
    open: Number(c.open),
    high: Number(c.high),
    low: Number(c.low),
    close: Number(c.close),
    volume: Number(c.volume),
  }))
}
