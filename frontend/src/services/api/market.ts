// Market data service calls for the POC pages: the instrument list, daily series and the
// market environments. Every price is a decimal string on the wire; the chart converts to
// numbers only to draw. Interval filtering and metrics are served by the same API (candles
// and metrics routes) but the prototype has no control for them, so no page asks for them.

import type { MarketEnvironment } from '../../types'
import type { MarketComponents } from '../generated'
import { apiGet, apiPost } from './typed'

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

export type Interval = MarketComponents['schemas']['CandleSeries']['interval']
/** The metrics of a window, as the API describes them (ratios as decimal strings). */
export type Metrics = MarketComponents['schemas']['MetricsOut']

export const INTERVALS: { value: Interval; label: string }[] = [
  { value: 'daily', label: 'Daily' },
  { value: 'weekly', label: 'Weekly' },
  { value: 'monthly', label: 'Monthly' },
  { value: 'yearly', label: 'Yearly' },
]

/** How many candles the default window shows, and what one candle is called. */
export const DEFAULT_WINDOW: Record<Interval, { buckets: number; unit: string }> = {
  daily: { buckets: 90, unit: 'sessions' },
  weekly: { buckets: 104, unit: 'weeks' },
  monthly: { buckets: 60, unit: 'months' },
  yearly: { buckets: 20, unit: 'years' },
}

/** Calendar days one candle spans at most, with room for weekends and holidays. */
const DAYS_PER_BUCKET: Record<Interval, number> = { daily: 1.6, weekly: 7.5, monthly: 31, yearly: 366 }

export interface Candle {
  /** The first session the candle covers (the session itself for a daily candle). */
  date: string
  /** The last session the candle covers; with `date` it is the candle's exact window. */
  lastSession?: string
  open: number
  high: number
  low: number
  close: number
  volume: number
}

type ApiCandle = MarketComponents['schemas']['CandleOut']

export async function listInstruments(status: 'active' | 'retired' | null = 'active'): Promise<MarketInstrument[]> {
  const rows = await apiGet('/api/market/instruments', { query: { status } })
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
  return getRecentSeries(instrumentId, 'daily', sessions)
}

/** The latest `buckets` candles of an interval, with the same reach-back rule as above. */
export async function getRecentSeries(
  instrumentId: string,
  interval: Interval,
  buckets: number = DEFAULT_WINDOW[interval].buckets,
): Promise<Candle[]> {
  const from = new Date()
  from.setUTCDate(from.getUTCDate() - Math.ceil(buckets * DAYS_PER_BUCKET[interval]) - 10)
  let candles = await getCandleSeries(instrumentId, { interval, from: from.toISOString().slice(0, 10) })
  if (candles.length === 0) candles = await getCandleSeries(instrumentId, { interval })
  return candles.slice(-buckets)
}

export interface CandleWindow {
  interval: Interval
  from?: string
  to?: string
}

/** Candles of one interval over an optional date window, oldest first. */
export async function getCandleSeries(instrumentId: string, window: CandleWindow): Promise<Candle[]> {
  const body = await apiGet('/api/market/instruments/{instrument_id}/candles', {
    path: { instrument_id: instrumentId },
    query: { interval: window.interval, from: window.from, to: window.to },
  })
  return body.items.map(toCandle)
}

/** Period return, volatility and drawdown over the same kind of window. */
export function getMetrics(instrumentId: string, window: CandleWindow): Promise<Metrics> {
  return apiGet('/api/market/instruments/{instrument_id}/metrics', {
    path: { instrument_id: instrumentId },
    query: { interval: window.interval, from: window.from, to: window.to },
  })
}

function toCandle(c: ApiCandle): Candle {
  return {
    date: c.period_start ?? c.session_date,
    lastSession: c.session_date,
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
  return getCandleSeries(instrumentId, { interval: 'daily', from, to })
}
