// Pure data-generation helpers backing the mock visualizations. None of this
// is a real stochastic engine — it produces visually convincing, deterministic
// series so charts look and move like the real product would.

import { gaussian, mulberry32 } from '../../utils/random'

/** Simulated GBM-style price paths for the Monte Carlo fan chart. */
export function generateMonteCarloPaths(opts: {
  seed: number
  paths: number
  steps: number
  start: number
  drift: number
  vol: number
}) {
  const { seed, paths, steps, start, drift, vol } = opts
  const rand = mulberry32(seed)
  const dt = 1 / 252
  const series: number[][] = []
  for (let p = 0; p < paths; p++) {
    const path: number[] = [start]
    let s = start
    for (let t = 1; t <= steps; t++) {
      const shock = gaussian(rand)
      s = s * Math.exp((drift - 0.5 * vol * vol) * dt + vol * Math.sqrt(dt) * shock)
      path.push(s)
    }
    series.push(path)
  }
  return series
}

export function pathPercentiles(series: number[][], step: number, pct: number) {
  const values = series.map((s) => s[step]).sort((a, b) => a - b)
  const idx = Math.min(values.length - 1, Math.max(0, Math.floor((pct / 100) * values.length)))
  return values[idx]
}

/** Historical-looking OHLC candle series. */
export function generateCandles(opts: { seed: number; count: number; start: number; vol: number }) {
  const { seed, count, start, vol } = opts
  const rand = mulberry32(seed)
  let last = start
  const candles: { date: string; open: number; high: number; low: number; close: number; volume: number }[] = []
  const today = new Date('2026-06-30T00:00:00Z')
  for (let i = count - 1; i >= 0; i--) {
    const d = new Date(today)
    d.setDate(d.getDate() - i)
    const open = last
    const change = gaussian(rand) * vol * open
    const close = Math.max(1, open + change)
    const high = Math.max(open, close) + Math.abs(gaussian(rand)) * vol * open * 0.4
    const low = Math.min(open, close) - Math.abs(gaussian(rand)) * vol * open * 0.4
    const volume = Math.round(1_000_000 + rand() * 4_000_000)
    candles.push({ date: d.toISOString().slice(0, 10), open, high, low, close, volume })
    last = close
  }
  return candles
}

/** Symmetric correlation matrix, biased so it can visibly "converge toward 1". */
export function generateCorrelationMatrix(assets: string[], seed: number, convergence = 0) {
  const rand = mulberry32(seed)
  const n = assets.length
  const m: number[][] = Array.from({ length: n }, () => Array(n).fill(0))
  for (let i = 0; i < n; i++) {
    for (let j = i; j < n; j++) {
      if (i === j) {
        m[i][j] = 1
      } else {
        const base = 0.15 + rand() * 0.45
        const val = base + convergence * (0.95 - base)
        m[i][j] = Number(val.toFixed(2))
        m[j][i] = m[i][j]
      }
    }
  }
  return m
}

export function correlationToDistance(corr: number[][]) {
  return corr.map((row) => row.map((c) => Number(Math.sqrt(2 * (1 - c)).toFixed(3))))
}

/** Deterministic persistence-diagram-like point cloud. */
export function generatePersistencePoints(seed: number, count: number, dim: 0 | 1, spread: number) {
  const rand = mulberry32(seed)
  const points: { birth: number; death: number; dim: 0 | 1 }[] = []
  for (let i = 0; i < count; i++) {
    const birth = Number((rand() * 0.4 * spread).toFixed(3))
    const death = Number((birth + rand() * 0.6 * spread + 0.05).toFixed(3))
    points.push({ birth, death, dim })
  }
  return points
}

export function generateLandscapeCurves(seed: number, curveCount: number, resolution: number) {
  const rand = mulberry32(seed)
  const curves: number[][] = []
  for (let c = 0; c < curveCount; c++) {
    const peak = 0.3 + rand() * 0.6 - c * 0.08
    const center = resolution * (0.3 + rand() * 0.4)
    const width = resolution * (0.12 + rand() * 0.08)
    const curve: number[] = []
    for (let x = 0; x < resolution; x++) {
      const v = Math.max(0, peak * Math.exp(-((x - center) ** 2) / (2 * width * width)))
      curve.push(Number(v.toFixed(3)))
    }
    curves.push(curve)
  }
  return curves
}

export function generateEquityCurve(opts: { seed: number; days: number; start: number; drift: number; vol: number }) {
  const { seed, days, start, drift, vol } = opts
  const rand = mulberry32(seed)
  let v = start
  const out: { day: number; value: number }[] = [{ day: 0, value: v }]
  for (let d = 1; d <= days; d++) {
    v = v * (1 + drift / days + vol * gaussian(rand) * Math.sqrt(1 / days))
    out.push({ day: d, value: v })
  }
  return out
}

export function generateDrawdownSeries(equity: { day: number; value: number }[]) {
  let peak = -Infinity
  return equity.map((e) => {
    peak = Math.max(peak, e.value)
    return { day: e.day, drawdown: ((e.value - peak) / peak) * 100 }
  })
}
