import type { SimulationComponents } from '../../../services/generated'

type Schemas = SimulationComponents['schemas']

// Typed against the generated schema, so a renamed or removed field fails the type check here too.
export const AAPL = '8d0aba1d-1737-59a8-8b52-846d1791226f'
export const MSFT = '0b6d7f3a-1111-4a00-8000-000000000002'
const USER = '9d1e5c7b-2222-4b00-8000-000000000001'

export const gbmFit: Schemas['Fit'] = {
  model: 'gbm',
  instrument_id: AAPL,
  symbol: 'AAPL',
  window_start: '2020-01-02',
  window_end: '2020-12-31',
  params: { mu: 0.62, sigma: 0.49 },
  std_errors: { mu: 0.31, sigma: 0.02 },
  log_likelihood: '694.1234567890',
  aic: '-1384.2469135780',
  n_obs: 252,
  converged: true,
  input_fingerprint: 'xxh3:3f9a1c0e5b7d2a48c6e10f93b5d7a2c1',
  qs_quant_version: '0.2.0',
  created_by: USER,
  created_at: '2026-11-19T10:00:01Z',
}

export const calibrations: Schemas['CalibrationOut'][] = [
  {
    id: '5b0e6f1c-2d3a-4c8b-9e7f-1a2b3c4d5e6f',
    status: 'succeeded',
    progress: 1,
    created_at: '2026-11-19T10:00:00Z',
    finished_at: '2026-11-19T10:00:01Z',
    calibration: gbmFit,
    refusal: null,
    error: null,
  },
  {
    id: '5b0e6f1c-2d3a-4c8b-9e7f-1a2b3c4d5e70',
    status: 'succeeded',
    progress: 1,
    created_at: '2026-11-18T10:00:00Z',
    finished_at: '2026-11-18T10:00:01Z',
    calibration: {
      ...gbmFit,
      model: 'ou',
      instrument_id: MSFT,
      symbol: 'MSFT',
      params: { kappa: 8.2, theta: 5.1, sigma: 0.3 },
      std_errors: { kappa: 1.1, theta: 0.04, sigma: 0.01 },
      converged: false,
    },
    refusal: null,
    error: null,
  },
]

const summary = (id: string, over: Partial<Schemas['RunSummary']>): Schemas['RunSummary'] => ({
  id,
  status: 'completed',
  model: 'gbm',
  n_paths: 1000,
  n_steps: 252,
  symbols: ['AAPL'],
  median_path_index: 417,
  parent_run_id: null,
  scenario: null,
  created_at: '2026-11-20T10:00:00Z',
  ...over,
})

export const BASE_RUN = 'a4d3c2b1-7e6f-4a5b-8c9d-0e1f2a3b4c5d'
export const STRESSED_RUN = 'a4d3c2b1-7e6f-4a5b-8c9d-0e1f2a3b4c5e'
export const RUNNING_RUN = 'a4d3c2b1-7e6f-4a5b-8c9d-0e1f2a3b4c5f'

export const runs: Schemas['RunSummary'][] = [
  summary(RUNNING_RUN, { status: 'running', median_path_index: null, created_at: '2026-11-22T10:00:00Z' }),
  summary(STRESSED_RUN, { parent_run_id: BASE_RUN, scenario: 'flash_crash', created_at: '2026-11-21T10:00:00Z' }),
  summary(BASE_RUN, { symbols: ['AAPL', 'MSFT'], model: 'merton' }),
  summary('a4d3c2b1-7e6f-4a5b-8c9d-0e1f2a3b4c60', { status: 'failed', median_path_index: null, n_paths: 800 }),
]

const stats = (symbol: string, id: string): Schemas['InstrumentStatistics'] => ({
  instrument_id: id,
  symbol,
  mean_price: '151.2300000000',
  median_price: '149.8800000000',
  p5_price: '98.1000000000',
  p95_price: '221.7000000000',
  var95: '0.2312000000',
  cvar95: '0.3105000000',
})

export const baseRun: Schemas['RunOut'] = {
  ...runs[2],
  progress: 1,
  seed: 42,
  storage_mode: 'full',
  statistics: [stats('AAPL', AAPL), stats('MSFT', MSFT)],
  error: null,
}

export const stressedRun: Schemas['RunOut'] = {
  ...runs[1],
  progress: 1,
  seed: 42,
  storage_mode: 'full',
  statistics: [
    { ...stats('AAPL', AAPL), mean_price: '121.0000000000', var95: '0.3400000000', cvar95: '0.4100000000' },
  ],
  error: null,
}

export const runningRun: Schemas['RunOut'] = {
  ...runs[0],
  progress: 0.4,
  seed: 7,
  storage_mode: 'full',
  statistics: [],
  error: null,
}

const step = (n: number, scale: number): Schemas['QuantileStep'] => ({
  step: n,
  q01: (80 * scale).toFixed(10),
  q05: (90 * scale).toFixed(10),
  q25: (100 * scale).toFixed(10),
  q50: (110 * scale).toFixed(10),
  q75: (125 * scale).toFixed(10),
  q95: (150 * scale).toFixed(10),
  q99: (175 * scale).toFixed(10),
})

export const quantiles = (runId: string, scale = 1): Schemas['QuantilesOut'] => ({
  run_id: runId,
  n_steps: 3,
  levels: { q01: '0.01', q05: '0.05', q25: '0.25', q50: '0.50', q75: '0.75', q95: '0.95', q99: '0.99' },
  instruments: [
    {
      instrument_id: AAPL,
      symbol: 'AAPL',
      start_price: '100.0000000000',
      steps: [step(1, scale), step(2, scale * 1.02), step(3, scale * 1.04)],
    },
  ],
})

export const scenarios: Schemas['ScenarioOut'][] = [
  {
    id: '7c1f0b2a-3d4e-4f50-8a6b-9c0d1e2f3a4b',
    code: 'flash_crash',
    name: 'Flash crash: 20% in one step',
    type: 'price_shock',
    params: { drop: 0.2, at_step: 21, recovery_steps: 0 },
    created_at: '2026-11-22T10:00:00Z',
  },
  {
    id: '7c1f0b2a-3d4e-4f50-8a6b-9c0d1e2f3a4c',
    code: 'vol_spike',
    name: 'Volatility spike: three times normal for two months',
    type: 'vol_multiplier',
    params: { multiplier: 3, from_step: 21, to_step: 63 },
    created_at: '2026-11-22T10:00:00Z',
  },
]
