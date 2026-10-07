export default function CorrelationHeatmap({
  assets,
  matrix,
  cellLabel = 'ρ',
  colorFor,
}: {
  assets: string[]
  matrix: number[][]
  cellLabel?: string
  colorFor?: (v: number) => string
}) {
  // Single-hue sequential ramp: near-white at 0 -> the severe risk crimson at
  // 1. The previous ramp ran blue -> red and passed through dark muddy
  // mid-tones, which read as a second category and swallowed the cell label.
  const RAMP_LOW = [242, 245, 248]
  const RAMP_HIGH = [161, 15, 61]
  const defaultColor = (v: number) => {
    const t = Math.max(0, Math.min(1, v))
    const [r, g, b] = RAMP_LOW.map((lo, i) => Math.round(lo + t * (RAMP_HIGH[i] - lo)))
    return `rgb(${r},${g},${b})`
  }
  const color = colorFor ?? defaultColor

  // Pick the label ink from the cell's own luminance so it never sinks into a
  // dark cell - a fixed near-black label failed on the top half of any ramp.
  const labelInk = (fill: string) => {
    const m = fill.match(/rgb\((\d+),\s*(\d+),\s*(\d+)\)/)
    if (!m) return 'var(--color-text-primary)'
    const lin = [1, 2, 3]
      .map((i) => Number(m[i]) / 255)
      .map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4))
    const lum = 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]
    return lum > 0.42 ? '#0a0d12' : '#ffffff'
  }
  const cell = 52

  return (
    <div className="overflow-x-auto">
      <svg
        viewBox={`0 0 ${cell * (assets.length + 1) + 10} ${cell * (assets.length + 1) + 10}`}
        style={{ width: cell * (assets.length + 1) + 10, height: cell * (assets.length + 1) + 10, display: 'block', margin: '0 auto' }}
      >
        {assets.map((a, i) => (
          <text key={`ch-${a}`} x={cell * (i + 1) + cell / 2} y={16} fontSize={10} textAnchor="middle" fill="var(--color-text-muted)" className="mono">
            {a}
          </text>
        ))}
        {assets.map((a, i) => (
          <text key={`rh-${a}`} x={cell / 2} y={cell * (i + 1) + cell / 2 + 4} fontSize={10} textAnchor="middle" fill="var(--color-text-muted)" className="mono">
            {a}
          </text>
        ))}
        {matrix.map((row, i) =>
          row.map((v, j) => (
            <g key={`${i}-${j}`}>
              <rect
                x={cell * (j + 1) + 2}
                y={cell * (i + 1) + 2}
                width={cell - 4}
                height={cell - 4}
                rx={3}
                fill={color(v)}
              />
              <text
                x={cell * (j + 1) + cell / 2}
                y={cell * (i + 1) + cell / 2 + 4}
                fontSize={10.5}
                textAnchor="middle"
                fill={labelInk(color(v))}
                fontWeight={600}
              >
                {cellLabel === 'ρ' ? v.toFixed(2) : v.toFixed(2)}
              </text>
            </g>
          )),
        )}
      </svg>
    </div>
  )
}
