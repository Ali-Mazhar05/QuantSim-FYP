import { useMemo } from 'react'
import { generateCandles } from '../../services/mock/generators'
import { useElementWidth } from '../../hooks/useElementWidth'

export default function CandlestickChart({
  seed = 1,
  start = 200,
  vol = 0.02,
  count = 90,
  height = 260,
}: {
  seed?: number
  start?: number
  vol?: number
  count?: number
  height?: number
}) {
  const candles = useMemo(() => generateCandles({ seed, count, start, vol }), [seed, count, start, vol])
  const [wrapRef, available] = useElementWidth<HTMLDivElement>()
  // Draw at the panel's real width so the candles widen to fill it. Below
  // MIN_WIDTH the chart keeps its own size and the wrapper scrolls instead,
  // which is the only case where the candles would otherwise be unreadable.
  const MIN_WIDTH = Math.max(360, count * 4)
  const width = Math.max(MIN_WIDTH, available || MIN_WIDTH)
  const cw = width / count
  const highs = candles.map((c) => c.high)
  const lows = candles.map((c) => c.low)
  const minV = Math.min(...lows) * 0.98
  const maxV = Math.max(...highs) * 1.02
  const y = (v: number) => height - ((v - minV) / (maxV - minV)) * height

  return (
    <div ref={wrapRef} className="w-full overflow-x-auto">
      <svg
        viewBox={`0 0 ${width} ${height + 20}`}
        width={width}
        height={height + 20}
        style={{ display: 'block' }}
      >
        {[0, 0.25, 0.5, 0.75, 1].map((f) => (
          <line key={f} x1={0} x2={width} y1={height * f} y2={height * f} stroke="var(--color-border)" strokeWidth={1} />
        ))}
        {candles.map((c, i) => {
          const cx = i * cw + cw / 2
          const up = c.close >= c.open
          const color = up ? 'var(--color-risk-low)' : 'var(--color-risk-severe)'
          return (
            <g key={c.date}>
              <line x1={cx} x2={cx} y1={y(c.high)} y2={y(c.low)} stroke={color} strokeWidth={1} />
              <rect
                x={cx - cw * 0.32}
                y={Math.min(y(c.open), y(c.close))}
                width={cw * 0.64}
                height={Math.max(1, Math.abs(y(c.close) - y(c.open)))}
                fill={color}
              />
            </g>
          )
        })}
        <line x1={0} x2={width} y1={height} y2={height} stroke="var(--color-border-strong)" />
      </svg>
    </div>
  )
}
