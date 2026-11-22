// Simulation service calls on the generated types: calibrations, runs, quantiles and scenarios are
// all typed from the service's OpenAPI document. Prices and statistics are decimal strings on the
// wire; they are converted to numbers only to draw.

import type { SimulationComponents } from '../generated'
import { apiGet, apiPost, type RequestOptions } from './typed'

type Schemas = SimulationComponents['schemas']
export type Calibration = Schemas['CalibrationOut']
export type CalibrationFit = NonNullable<Calibration['calibration']>
export type RunSummary = Schemas['RunSummary']
export type Run = Schemas['RunOut']
export type RunCreate = Schemas['RunCreate']
export type CalibrationCreate = Schemas['CalibrationCreate']
export type Quantiles = Schemas['QuantilesOut']
export type Scenario = Schemas['ScenarioOut']
export type ModelName = Run['model']

const BASE = '/api/simulation'
/** The page size the lists ask for: the service's maximum, so one read covers a demo. */
export const PAGE = 2000

export interface RunFilter {
  status?: RunSummary['status']
  instrument?: string
}

/** Every page of a list, following `next_cursor` (a bound stops a cursor that never ends). */
async function allPages<T>(
  read: (cursor: string | undefined) => Promise<{ items: T[]; next_cursor: string | null }>,
): Promise<T[]> {
  const items: T[] = []
  let cursor: string | undefined
  for (let page = 0; page < 50; page += 1) {
    const answer = await read(cursor)
    items.push(...answer.items)
    if (!answer.next_cursor) break
    cursor = answer.next_cursor
  }
  return items
}

const keyed = (key?: string) => (key ? { headers: { 'Idempotency-Key': key } } : undefined)

export function listRuns(filter: RunFilter = {}, options: RequestOptions = {}): Promise<RunSummary[]> {
  return allPages((cursor) => apiGet(`${BASE}/runs`, { query: { ...filter, limit: PAGE, cursor }, ...options }))
}

export const getRun = (id: string, options: RequestOptions = {}): Promise<Run> =>
  apiGet(`${BASE}/runs/{run_id}`, { path: { run_id: id }, ...options })

export const getQuantiles = (id: string, instrument?: string, options: RequestOptions = {}): Promise<Quantiles> =>
  apiGet(`${BASE}/runs/{run_id}/quantiles`, { path: { run_id: id }, query: { instrument }, ...options })

export const createRun = (body: RunCreate, idempotencyKey?: string): Promise<Run> =>
  apiPost(`${BASE}/runs`, body, keyed(idempotencyKey))

export const stressRun = (id: string, scenario: string, idempotencyKey?: string): Promise<Run> =>
  apiPost(`${BASE}/runs/{run_id}/scenarios`, { scenario }, { path: { run_id: id }, ...keyed(idempotencyKey) })

export function listCalibrations(options: RequestOptions = {}): Promise<Calibration[]> {
  return allPages((cursor) => apiGet(`${BASE}/calibrations`, { query: { limit: PAGE, cursor }, ...options }))
}

export const getCalibration = (id: string, options: RequestOptions = {}): Promise<Calibration> =>
  apiGet(`${BASE}/calibrations/{calibration_id}`, { path: { calibration_id: id }, ...options })

export const createCalibration = (body: CalibrationCreate, idempotencyKey?: string): Promise<Calibration> =>
  apiPost(`${BASE}/calibrations`, body, keyed(idempotencyKey))

export const listScenarios = (options: RequestOptions = {}): Promise<Scenario[]> =>
  apiGet(`${BASE}/scenarios`, options)

/** Where a job ends: nothing more will change, so polling stops. */
export const isFinished = (status: RunSummary['status'] | Calibration['status']): boolean =>
  status === 'completed' || status === 'failed' || status === 'succeeded' || status === 'refused'

/** The numbers a fan chart draws, from one instrument of the stored quantiles. */
export function fanOf(q: Quantiles, instrumentId?: string) {
  const one = q.instruments.find((i) => i.instrument_id === instrumentId) ?? q.instruments[0]
  if (!one) return null
  const column = (level: 'q05' | 'q25' | 'q50' | 'q75' | 'q95') => [
    Number(one.start_price),
    ...one.steps.map((s) => Number(s[level])),
  ]
  return {
    symbol: one.symbol,
    start: Number(one.start_price),
    bands: { p5: column('q05'), p25: column('q25'), p50: column('q50'), p75: column('q75'), p95: column('q95') },
  }
}

/** A calibration the model refused (too little history, not mean-reverting ...), with its reason. */
export class CalibrationRefusedError extends Error {
  readonly symbol: string
  readonly reason: string

  constructor(symbol: string, reason: string) {
    super(`${symbol}: ${reason}`)
    this.name = 'CalibrationRefusedError'
    this.symbol = symbol
    this.reason = reason
  }
}

const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms))

export interface EnsureOptions {
  model: ModelName
  instruments: { id: string; symbol: string }[]
  start: string
  end: string
  /** The stored calibrations already known, to reuse a fit of the same model and window. */
  existing: Calibration[]
  pollMs?: number
  /** Give up waiting for a fit after this long (the job itself keeps its own limits). */
  timeoutMs?: number
}

/**
 * The calibration of every instrument for a model and window: a converged stored fit of exactly
 * that window is reused, anything else is fitted now (one job per instrument, started together)
 * and waited for. A refusal stops the whole thing with the model's own reason.
 */
export async function ensureCalibrations(options: EnsureOptions): Promise<string[]> {
  const { model, start, end, existing, pollMs = 1000, timeoutMs = 120_000 } = options
  return Promise.all(
    options.instruments.map(async ({ id, symbol }) => {
      const reusable = existing.find(
        (c) =>
          c.calibration?.instrument_id === id &&
          c.calibration.model === model &&
          c.calibration.converged &&
          c.calibration.window_start === start &&
          c.calibration.window_end === end,
      )
      if (reusable) return reusable.id
      let job = await createCalibration(
        { instrument_id: id, model, window_start: start, window_end: end },
        `ui:calibrate:${model}:${id}:${start}:${end}`,
      )
      const deadline = Date.now() + timeoutMs
      while (!isFinished(job.status)) {
        if (Date.now() > deadline) throw new Error(`${symbol}: the fit did not finish in time`)
        await sleep(pollMs)
        job = await getCalibration(job.id)
      }
      if (job.status === 'refused') throw new CalibrationRefusedError(symbol, job.refusal?.reason ?? 'refused')
      if (job.status === 'failed') throw new Error(`${symbol}: ${job.error ?? 'the fit failed'}`)
      if (!job.calibration?.converged) throw new CalibrationRefusedError(symbol, 'the fit did not converge')
      return job.id
    }),
  )
}
