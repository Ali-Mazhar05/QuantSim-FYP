// Trading API calls for the five trading pages: plain typed wrappers over the app's
// authenticated request helper, until the shared typed client (K4) replaces them. The
// response types are written from the service's schemas (services/trading schemas.py).
// Money, prices and fractions stay decimal strings end to end; pages turn them into
// numbers only to format them for display.

import { apiRequest } from '../../services/api/client'

const BASE = '/api/trading'

// ---- Strategies ----

export type StrategyKind = 'buy_and_hold' | 'momentum' | 'ma_crossover' | 'mean_reversion'

export const STRATEGY_KINDS: { kind: StrategyKind; label: string }[] = [
  { kind: 'buy_and_hold', label: 'Buy and Hold' },
  { kind: 'momentum', label: 'Momentum' },
  { kind: 'ma_crossover', label: 'Moving-Average Crossover' },
  { kind: 'mean_reversion', label: 'Mean Reversion' },
]

export function kindLabel(kind: string): string {
  return STRATEGY_KINDS.find((k) => k.kind === kind)?.label ?? kind
}

/** Stored parameters, defaults filled in: whole numbers as numbers, fractions as strings. */
export type StrategyParams = Record<string, unknown>

export interface Strategy {
  id: string
  name: string
  kind: string
  params: StrategyParams
  owner_id: string
  created_at: string
  updated_at: string
}

export interface StrategyInput {
  name: string
  kind: StrategyKind
  params: StrategyParams
}

export function listStrategies(): Promise<Strategy[]> {
  return apiRequest<Strategy[]>(`${BASE}/strategies`)
}

export function getStrategy(id: string): Promise<Strategy> {
  return apiRequest<Strategy>(`${BASE}/strategies/${encodeURIComponent(id)}`)
}

export function createStrategy(input: StrategyInput): Promise<Strategy> {
  return apiRequest<Strategy>(`${BASE}/strategies`, { method: 'POST', body: JSON.stringify(input) })
}

export function replaceStrategy(id: string, input: StrategyInput): Promise<Strategy> {
  return apiRequest<Strategy>(`${BASE}/strategies/${encodeURIComponent(id)}`, {
    method: 'PUT',
    body: JSON.stringify(input),
  })
}

// ---- Portfolios ----

export interface CostModel {
  fixed: string
  per_share: string
  pct: string
}

export interface SlippageModel {
  kind: 'fixed_bps' | 'volume'
  bps: string
}

export interface Portfolio {
  id: string
  name: string
  strategy_id: string
  strategy_name: string
  strategy_kind: string
  owner_id: string
  /** USD, 2 decimal places. */
  initial_capital: string
  base_currency: string
  cost_model: CostModel
  slippage_model: SlippageModel
  env_type: 'replay' | 'simulation'
  replay_environment_id: string | null
  simulation_run_id: string | null
  path_index: number | null
  /** Frozen by the first run; null until the portfolio has run. */
  source_fingerprint: string | null
  created_at: string
  updated_at: string
}

export interface PortfolioInput {
  name: string
  strategy_id: string
  initial_capital: string
  cost_model: CostModel
  slippage_model: SlippageModel
  replay_environment_id?: string
  simulation_run_id?: string
  path_index?: number
}

export function listPortfolios(): Promise<Portfolio[]> {
  return apiRequest<Portfolio[]>(`${BASE}/portfolios`)
}

export function getPortfolio(id: string): Promise<Portfolio> {
  return apiRequest<Portfolio>(`${BASE}/portfolios/${encodeURIComponent(id)}`)
}

export function createPortfolio(input: PortfolioInput): Promise<Portfolio> {
  return apiRequest<Portfolio>(`${BASE}/portfolios`, { method: 'POST', body: JSON.stringify(input) })
}

// ---- Runs ----

export type RunStatus = 'queued' | 'running' | 'succeeded' | 'failed'

export interface RunAccepted {
  job_id: string
  portfolio_id: string
  status: RunStatus
  /** False when the portfolio's run job already existed. */
  created: boolean
}

export interface Run {
  job_id: string
  portfolio_id: string
  status: RunStatus
  /** Sessions committed / sessions in total, 0 to 1. */
  progress: number
  attempts: number
  max_attempts: number
  error: string | null
  result: Record<string, unknown> | null
  created_at: string
  started_at: string | null
  finished_at: string | null
}

/** A fresh key for one attempt to start a run. */
export function newRunKey(): string {
  return crypto.randomUUID()
}

/** Queues a run of the portfolio. `idempotencyKey` identifies this attempt: sending the same
 * key again (a retry) answers with the same job (`created: false`) instead of starting a
 * second run; a new key starts a new run once the previous one has finished. */
export function startRun(portfolioId: string, idempotencyKey: string): Promise<RunAccepted> {
  return apiRequest<RunAccepted>(`${BASE}/portfolios/${encodeURIComponent(portfolioId)}/runs`, {
    method: 'POST',
    headers: { 'Idempotency-Key': idempotencyKey },
  })
}

export function getRun(portfolioId: string, jobId: string): Promise<Run> {
  return apiRequest<Run>(`${BASE}/portfolios/${encodeURIComponent(portfolioId)}/runs/${encodeURIComponent(jobId)}`)
}

const RUNS_KEY = 'qs.trading.runs'

/** The run jobs started from this browser, by portfolio, so the Portfolios page can show
 * their status (the API has no "runs of a portfolio" list yet). */
export function rememberedRuns(): Record<string, string> {
  try {
    const parsed: unknown = JSON.parse(window.localStorage.getItem(RUNS_KEY) ?? '{}')
    return parsed && typeof parsed === 'object' ? (parsed as Record<string, string>) : {}
  } catch {
    return {}
  }
}

export function rememberRun(portfolioId: string, jobId: string): void {
  try {
    window.localStorage.setItem(RUNS_KEY, JSON.stringify({ ...rememberedRuns(), [portfolioId]: jobId }))
  } catch {
    // storage unavailable: the status is still derived from the log
  }
}

/** How often a queued or running backtest is asked for its status. */
export const RUN_POLL_MS = 1000

// ---- Trade log and projections ----

export type EventType =
  | 'RUN_STARTED'
  | 'TICK'
  | 'ORDER_PLACED'
  | 'ORDER_REJECTED'
  | 'ORDER_FILLED'
  | 'ORDER_EXPIRED'
  | 'VALUED'
  | 'RUN_COMPLETED'

export interface TradeLogEvent {
  seq: number
  type: EventType | string
  version: number
  event_time: string
  /** Amounts and prices as decimal strings. */
  payload: Record<string, unknown>
  prev_hash: string | null
  hash: string
}

export interface Page<T> {
  items: T[]
  /** after_seq of the next page; null on the last page. */
  next_cursor: number | null
}

export function listEvents(portfolioId: string, afterSeq = 0, limit = 500): Promise<Page<TradeLogEvent>> {
  const query = new URLSearchParams({ after_seq: String(afterSeq), limit: String(limit) })
  return apiRequest<Page<TradeLogEvent>>(`${BASE}/portfolios/${encodeURIComponent(portfolioId)}/events?${query}`)
}

export interface ValuePoint {
  session: number
  ts: string
  /** The VALUED event. */
  seq: number
  cash: string
  market_value: string
  value: string
  realised_pnl: string
  unrealised_pnl: string
  total_costs: string
}

export function getValueSeries(portfolioId: string): Promise<ValuePoint[]> {
  return apiRequest<ValuePoint[]>(`${BASE}/portfolios/${encodeURIComponent(portfolioId)}/value-series`)
}

export interface Metrics {
  portfolio_id: string
  /** The last event folded in; 0 before the first run. */
  final_seq: number
  final_hash: string | null
  sessions: number
  initial_capital: string
  final_value: string | null
  trades: number
  total_costs: string
  total_return: string | null
  volatility: string | null
  sharpe: string | null
  max_drawdown: string | null
  turnover: string | null
  pending: string[]
}

export function getMetrics(portfolioId: string): Promise<Metrics> {
  return apiRequest<Metrics>(`${BASE}/portfolios/${encodeURIComponent(portfolioId)}/metrics`)
}

// ---- Trade Replay playback ----

/** The replay speeds (ADR 06): events per base step. */
export const SPEEDS = [1, 5, 20]
/** Milliseconds per event at 1×; 5× and 20× divide it. */
export const BASE_STEP_MS = 700
/** Events per request when the log is paged in. */
export const EVENT_PAGE = 500

// ---- Environments a portfolio can be bound to ----

export interface DemoEnvironment {
  id: string
  name: string
  env_type: 'replay' | 'simulation'
  sessions: number
  start_date: string | null
  end_date: string | null
}

/** The bundled demo environments (DEV only; empty elsewhere). */
export function listDemoEnvironments(): Promise<DemoEnvironment[]> {
  return apiRequest<DemoEnvironment[]>(`${BASE}/demo-environments`)
}

// ---- Helpers ----

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

/** Whether `id` can name a record of the API (every id is a UUID). */
export function isId(id: string | undefined): id is string {
  return !!id && UUID.test(id)
}

/** A decimal string as US dollars, for display only. */
export function formatUsd(amount: string | null | undefined, digits = 0): string {
  if (amount === null || amount === undefined || amount === '') return '—'
  const value = Number(amount)
  if (!Number.isFinite(value)) return amount
  return `$${value.toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits })}`
}

/** A fraction such as "0.25" as a percentage such as "25%", for display only. */
export function formatFraction(fraction: unknown): string {
  const value = Number(fraction)
  if (fraction === null || fraction === undefined || !Number.isFinite(value)) return '—'
  return `${Number((value * 100).toFixed(4))}%`
}
