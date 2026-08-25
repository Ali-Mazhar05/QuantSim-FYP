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
  const defaultColor = (v: number) => {
    // 0 -> cool accent, 1 -> hot risk color
    const t = Math.max(0, Math.min(1, v))
    const r = Math.round(59 + t * (209 - 59))
    const g = Math.round(130 + t * (85 - 130))
    const b = Math.round(196 + t * (63 - 196))
    return `rgb(${r},${g},${b})`
  }
  const color = colorFor ?? defaultColor
  const cell = 52

  return (
    <div className="overflow-x-auto">
      <svg
        viewBox={`0 0 ${cell * (assets.length + 1) + 10} ${cell * (assets.length + 1) + 10}`}
        style={{ width: cell * (assets.length + 1) + 10, height: cell * (assets.length + 1) + 10 }}
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
                opacity={0.85}
              />
              <text
                x={cell * (j + 1) + cell / 2}
                y={cell * (i + 1) + cell / 2 + 4}
                fontSize={10.5}
                textAnchor="middle"
                fill="#0a0d12"
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
