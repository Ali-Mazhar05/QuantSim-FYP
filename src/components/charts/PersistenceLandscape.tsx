const COLORS = ['var(--color-accent-strong)', 'var(--color-risk-elevated)', 'var(--color-risk-high)', 'var(--color-text-secondary)']

export default function PersistenceLandscape({ curves, height = 200 }: { curves: number[][]; height?: number }) {
  const width = 600
  const resolution = curves[0]?.length ?? 1
  const x = (i: number) => (i / (resolution - 1)) * width
  const y = (v: number) => height - v * height

  return (
    <div className="w-full overflow-x-auto">
      <svg viewBox={`0 0 ${width} ${height + 24}`} className="w-full" style={{ minWidth: 480 }}>
        {[0, 0.25, 0.5, 0.75, 1].map((f) => (
          <line key={f} x1={0} x2={width} y1={height * (1 - f)} y2={height * (1 - f)} stroke="var(--color-border)" strokeWidth={1} />
        ))}
        {curves.map((curve, ci) => {
          const d = curve.map((v, i) => `${i === 0 ? 'M' : 'L'} ${x(i).toFixed(1)} ${y(v).toFixed(1)}`).join(' ')
          const area = `${d} L ${width} ${height} L 0 ${height} Z`
          return (
            <g key={ci}>
              <path d={area} fill={COLORS[ci % COLORS.length]} opacity={0.08} />
              <path d={d} fill="none" stroke={COLORS[ci % COLORS.length]} strokeWidth={1.75} />
            </g>
          )
        })}
        <line x1={0} x2={width} y1={height} y2={height} stroke="var(--color-border-strong)" />
      </svg>
      <div className="mt-2 flex flex-wrap gap-4 text-[11px] text-[var(--color-text-muted)]">
        {curves.map((_, i) => (
          <span key={i} className="flex items-center gap-1.5">
            <span className="h-0.5 w-3" style={{ background: COLORS[i % COLORS.length] }} />
            Landscape λ{i + 1}
          </span>
        ))}
      </div>
    </div>
  )
}
