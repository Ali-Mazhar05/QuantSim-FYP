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
