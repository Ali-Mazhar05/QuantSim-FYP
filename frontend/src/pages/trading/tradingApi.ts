// Trading API calls for the five trading pages, over the typed client (K4): the paths, bodies
// and responses come from the trading service's OpenAPI document (generated/trading), so a
// field renamed in the API fails the type check wherever a page used it. Money, prices and
// fractions stay decimal strings end to end; pages turn them into numbers only to format
// them for display.

import type { RequestOptions } from '../../services/api/typed'
import { apiGet, apiPost, apiPut } from '../../services/api/typed'
import type { TradingComponents } from '../../services/generated'

type Schemas = TradingComponents['schemas']

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
export type StrategyParams = Schemas['StrategyOut']['params']

export type Strategy = Schemas['StrategyOut']

/** The body of a create or replace; the kind is one the pages offer. */
export type StrategyInput = Schemas['StrategyIn'] & { kind: StrategyKind }

export function listStrategies(options: RequestOptions = {}): Promise<Strategy[]> {
  return apiGet('/api/trading/strategies', options)
}

export function getStrategy(id: string, options: RequestOptions = {}): Promise<Strategy> {
  return apiGet('/api/trading/strategies/{strategy_id}', { path: { strategy_id: id }, ...options })
}

export function createStrategy(input: StrategyInput, options: RequestOptions = {}): Promise<Strategy> {
  return apiPost('/api/trading/strategies', input, options)
}

export function replaceStrategy(id: string, input: StrategyInput, options: RequestOptions = {}): Promise<Strategy> {
  return apiPut('/api/trading/strategies/{strategy_id}', input, { path: { strategy_id: id }, ...options })
}

// ---- Portfolios ----

export type CostModel = Schemas['CostModelOut']

export type SlippageModel = Schemas['SlippageModelOut']

export type Portfolio = Schemas['PortfolioOut']

export type PortfolioInput = Schemas['PortfolioCreate']

export function listPortfolios(options: RequestOptions = {}): Promise<Portfolio[]> {
  return apiGet('/api/trading/portfolios', options)
}

export function getPortfolio(id: string, options: RequestOptions = {}): Promise<Portfolio> {
  return apiGet('/api/trading/portfolios/{portfolio_id}', { path: { portfolio_id: id }, ...options })
}

export function createPortfolio(input: PortfolioInput, options: RequestOptions = {}): Promise<Portfolio> {
  return apiPost('/api/trading/portfolios', input, options)
}

// ---- Runs ----

export type RunStatus = Schemas['RunOut']['status']

export type RunAccepted = Schemas['RunAccepted']

export type Run = Schemas['RunOut']

/** A fresh key for one attempt to start a run. */
export function newRunKey(): string {
  return crypto.randomUUID()
}

/** Queues a run of the portfolio. `idempotencyKey` identifies this attempt: sending the same
 * key again (a retry) answers with the same job (`created: false`) instead of starting a
 * second run; a new key starts a new run once the previous one has finished. */
export function startRun(
  portfolioId: string,
  idempotencyKey: string,
  options: { signal?: AbortSignal } = {},
): Promise<RunAccepted> {
  return apiPost('/api/trading/portfolios/{portfolio_id}/runs', undefined, {
    path: { portfolio_id: portfolioId },
    headers: { 'Idempotency-Key': idempotencyKey },
    ...options,
  })
}

export function getRun(portfolioId: string, jobId: string, options: RequestOptions = {}): Promise<Run> {
  return apiGet('/api/trading/portfolios/{portfolio_id}/runs/{job_id}', {
    path: { portfolio_id: portfolioId, job_id: jobId },
    ...options,
  })
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

/** One event of the trade log; `type` is an EventType, payload amounts are decimal strings. */
export type TradeLogEvent = Schemas['EventOut']

export type EventPage = Schemas['EventPage']

export function listEvents(
  portfolioId: string,
  afterSeq = 0,
  limit = 500,
  options: RequestOptions = {},
): Promise<EventPage> {
  return apiGet('/api/trading/portfolios/{portfolio_id}/events', {
    path: { portfolio_id: portfolioId },
    query: { after_seq: afterSeq, limit },
    ...options,
  })
}

export type ValuePoint = Schemas['ValuePointOut']

export function getValueSeries(portfolioId: string, options: RequestOptions = {}): Promise<ValuePoint[]> {
  return apiGet('/api/trading/portfolios/{portfolio_id}/value-series', { path: { portfolio_id: portfolioId }, ...options })
}

export type Metrics = Schemas['MetricsOut']

export function getMetrics(portfolioId: string, options: RequestOptions = {}): Promise<Metrics> {
  return apiGet('/api/trading/portfolios/{portfolio_id}/metrics', { path: { portfolio_id: portfolioId }, ...options })
}

// ---- Trade Replay playback ----

/** The replay speeds (ADR 06): events per base step. */
export const SPEEDS = [1, 5, 20]
/** Milliseconds per event at 1×; 5× and 20× divide it. */
export const BASE_STEP_MS = 700
/** Events per request when the log is paged in. */
export const EVENT_PAGE = 500

// ---- Environments a portfolio can be bound to ----

export type DemoEnvironment = Schemas['DemoEnvironmentOut']

/** The bundled demo environments (DEV only; empty elsewhere). */
export function listDemoEnvironments(options: RequestOptions = {}): Promise<DemoEnvironment[]> {
  return apiGet('/api/trading/demo-environments', options)
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
