import { useMemo } from 'react'
import { generateMonteCarloPaths, pathPercentiles } from '../../services/mock/generators'
import { seriesOutcomeColor } from '../../utils/outcomeColor'

/** A fan from the service's stored quantiles: one value per step, the first being the start price. */
export interface FanBands {
  p5: number[]
  p25: number[]
  p50: number[]
  p75: number[]
  p95: number[]
}

export default function MonteCarloFanChart({
  start = 214.32,
  drift = 0.084,
  vol = 0.231,
  steps = 252,
  revealPct = 100,
  height = 300,
  bands,
  compare,
  compareLabel = 'Stressed median',
}: {
  start?: number
  drift?: number
  vol?: number
  steps?: number
  revealPct?: number
  height?: number
  /** Real quantiles: when given, the fan is drawn from them instead of generated paths. */
  bands?: FanBands
  /** A second median to draw over the fan (the stressed run beside the base). */
  compare?: number[]
  compareLabel?: string
}) {
  const stepsUsed = bands ? bands.p50.length - 1 : steps
  const { paths, mean, p5, p95, p25, p75 } = useMemo(() => {
    if (bands) return { paths: [] as number[][], mean: bands.p50, p5: bands.p5, p95: bands.p95, p25: bands.p25, p75: bands.p75 }
    const paths = generateMonteCarloPaths({ seed: 4242, paths: 60, steps, start, drift, vol })
    const mean: number[] = []
    const p5: number[] = []
    const p95: number[] = []
    const p25: number[] = []
    const p75: number[] = []
    for (let t = 0; t <= steps; t++) {
      const vals = paths.map((p) => p[t])
      mean.push(vals.reduce((a, b) => a + b, 0) / vals.length)
      p5.push(pathPercentiles(paths, t, 5))
      p95.push(pathPercentiles(paths, t, 95))
      p25.push(pathPercentiles(paths, t, 25))
      p75.push(pathPercentiles(paths, t, 75))
    }
    return { paths, mean, p5, p95, p25, p75 }
  }, [bands, steps, start, drift, vol])

  const width = 720
  const revealSteps = Math.round((revealPct / 100) * stepsUsed)
  const allVals = [...p5, ...p95, ...(compare ?? [])]
  const minV = Math.min(...allVals) * 0.96
  const maxV = Math.max(...allVals) * 1.04

  const x = (t: number) => (t / stepsUsed) * width
  const y = (v: number) => height - ((v - minV) / (maxV - minV)) * height

  const toPath = (series: number[], n: number) =>
    series
      .slice(0, n + 1)
      .map((v, i) => `${i === 0 ? 'M' : 'L'} ${x(i).toFixed(1)} ${y(v).toFixed(1)}`)
      .join(' ')

  const band = (upper: number[], lower: number[], n: number) => {
    const top = upper
      .slice(0, n + 1)
      .map((v, i) => `${i === 0 ? 'M' : 'L'} ${x(i).toFixed(1)} ${y(v).toFixed(1)}`)
      .join(' ')
    const bottomPts = lower.slice(0, n + 1)
    const bottom = bottomPts
      .map((_, i) => `L ${x(bottomPts.length - 1 - i).toFixed(1)} ${y(lower[bottomPts.length - 1 - i]).toFixed(1)}`)
      .join(' ')
    return `${top} ${bottom} Z`
  }

  const gridLines = 5
  const meanColor = useMemo(() => seriesOutcomeColor(mean.slice(0, revealSteps + 1)), [mean, revealSteps])

  return (
    <div className="w-full overflow-x-auto" data-testid="fan-chart">
      <svg viewBox={`0 0 ${width} ${height + 30}`} className="w-full" style={{ minWidth: 560 }}>
        {Array.from({ length: gridLines }).map((_, i) => {
          const v = minV + ((maxV - minV) / (gridLines - 1)) * i
          const yy = y(v)
          return (
            <g key={i}>
              <line x1={0} x2={width} y1={yy} y2={yy} stroke="var(--color-border)" strokeWidth={1} />
              <text x={4} y={yy - 4} fontSize={9} fill="var(--color-text-muted)" className="mono">
                ${v.toFixed(0)}
              </text>
            </g>
          )
        })}

        <path d={band(p95, p5, revealSteps)} fill="var(--color-accent)" opacity={0.08} />
        <path d={band(p75, p25, revealSteps)} fill="var(--color-accent)" opacity={0.16} />

        {paths.slice(0, 40).map((p, i) => (
          <path
            key={i}
            d={toPath(p, revealSteps)}
            fill="none"
            stroke="var(--color-accent)"
            strokeWidth={0.6}
            opacity={0.18}
          />
        ))}

        <path d={toPath(p5, revealSteps)} fill="none" stroke="var(--color-risk-elevated)" strokeWidth={1} strokeDasharray="3 3" opacity={0.7} />
        <path d={toPath(p95, revealSteps)} fill="none" stroke="var(--color-risk-elevated)" strokeWidth={1} strokeDasharray="3 3" opacity={0.7} />
        <path d={toPath(mean, revealSteps)} fill="none" stroke={meanColor} strokeWidth={2} />
        {compare && (
          <path d={toPath(compare, revealSteps)} fill="none" stroke="var(--color-risk-severe)" strokeWidth={2} strokeDasharray="6 3" data-testid="fan-compare" />
        )}

        <line x1={0} x2={width} y1={height} y2={height} stroke="var(--color-border)" />
        <text x={0} y={height + 18} fontSize={9} fill="var(--color-text-muted)" className="mono">Day 0</text>
        <text x={width - 40} y={height + 18} fontSize={9} fill="var(--color-text-muted)" className="mono">
          Day {stepsUsed}
        </text>
      </svg>
      <div className="mt-2 flex flex-wrap gap-4 text-[11px] text-[var(--color-text-muted)]">
        <span className="flex items-center gap-1.5"><span className="h-0.5 w-3" style={{ background: meanColor }} /> {bands ? "Median path" : "Mean path"}</span>
        {compare && <span className="flex items-center gap-1.5"><span className="h-0.5 w-3 border-t-2 border-dashed border-[var(--color-risk-severe)]" /> {compareLabel}</span>}
        <span className="flex items-center gap-1.5"><span className="h-0.5 w-3 border-t border-dashed border-[var(--color-risk-elevated)]" /> 5th / 95th percentile</span>
        <span className="flex items-center gap-1.5"><span className="h-2 w-3 bg-[var(--color-accent)] opacity-30" /> Confidence band</span>
        <span className="flex items-center gap-1.5"><span className="h-0.5 w-3 bg-[var(--color-accent)] opacity-40" /> Simulated paths</span>
      </div>
    </div>
  )
}
