// Market data service calls for the POC pages: the instrument list, daily series and the
// market environments. Every price is a decimal string on the wire; the chart converts to
// numbers only to draw. Interval filtering and metrics are served by the same API (candles
// and metrics routes) but the prototype has no control for them, so no page asks for them.

import type { MarketEnvironment } from '../../types'
import type { MarketComponents } from '../generated'
import { apiRequest } from './client'
import { apiGet, apiPost } from './typed'

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
  return body.items.slice(-sessions).map(toCandle)
}

function toCandle(c: ApiCandle): Candle {
  return {
    date: c.session_date,
    open: Number(c.open),
    high: Number(c.high),
    low: Number(c.low),
    close: Number(c.close),
    volume: Number(c.volume),
  }
}

// ---- Market environments (the prototype's Market Environments pages, field for field) ----

/** The API's environment, straight from the generated schema: a renamed field fails the type check. */
export type ApiEnvironment = MarketComponents['schemas']['EnvironmentOut']

const TYPE_NAMES: Record<ApiEnvironment['type'], MarketEnvironment['type']> = {
  historical_replay: 'Historical Replay',
  synthetic: 'Synthetic Market',
}
const TYPE_VALUES: Record<MarketEnvironment['type'], ApiEnvironment['type']> = {
  'Historical Replay': 'historical_replay',
  'Synthetic Market': 'synthetic',
}
const FREQUENCY_NAMES: Record<ApiEnvironment['frequency'], MarketEnvironment['frequency']> = {
  daily: 'Daily',
  hourly: 'Hourly',
  tick: 'Tick',
}
const FREQUENCY_VALUES: Record<MarketEnvironment['frequency'], ApiEnvironment['frequency']> = {
  Daily: 'daily',
  Hourly: 'hourly',
  Tick: 'tick',
}
const STATUS_NAMES: Record<ApiEnvironment['status'], MarketEnvironment['status']> = {
  draft: 'Draft',
  ready: 'Ready',
  active: 'Active',
}

/** An environment as the prototype's pages show it, with the instrument ids kept for requests. */
export interface Environment extends MarketEnvironment {
  instrumentIds: string[]
}

function toEnvironment(e: ApiEnvironment): Environment {
  return {
    id: e.id,
    name: e.name,
    type: TYPE_NAMES[e.type],
    universe: e.universe,
    instruments: e.symbols,
    instrumentIds: e.instrument_ids,
    start: e.start_date,
    end: e.end_date,
    frequency: FREQUENCY_NAMES[e.frequency],
    status: STATUS_NAMES[e.status],
  }
}

/** Every environment, newest first. */
export async function listEnvironments(): Promise<Environment[]> {
  return (await apiGet('/api/market/environments')).map(toEnvironment)
}

export async function createEnvironment(input: {
  name: string
  type: MarketEnvironment['type']
  universe: string
  instrumentIds: string[]
  start: string
  end: string
  frequency?: MarketEnvironment['frequency']
}): Promise<Environment> {
  const created = await apiPost('/api/market/environments', {
    name: input.name,
    type: TYPE_VALUES[input.type],
    universe: input.universe,
    instrument_ids: input.instrumentIds,
    start_date: input.start,
    end_date: input.end,
    frequency: FREQUENCY_VALUES[input.frequency ?? 'Daily'],
  })
  return toEnvironment(created)
}

/** Daily candles of an instrument over a window, oldest first. */
export async function getCandles(instrumentId: string, from: string, to: string): Promise<Candle[]> {
  const query = new URLSearchParams({ interval: 'daily', from, to })
  const body = await apiRequest<{ items: ApiCandle[] }>(`${BASE}/instruments/${instrumentId}/candles?${query}`)
  return body.items.map(toCandle)
}
