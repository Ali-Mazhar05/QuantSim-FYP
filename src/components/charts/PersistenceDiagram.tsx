export default function PersistenceDiagram({
  points,
  size = 320,
}: {
  points: { birth: number; death: number; dim: 0 | 1 }[]
  size?: number
}) {
  const max = Math.max(1, ...points.map((p) => p.death)) * 1.1
  const pad = 36
  const scale = (v: number) => pad + (v / max) * (size - pad * 1.5)

  return (
    <svg viewBox={`0 0 ${size} ${size}`} className="w-full" style={{ maxWidth: size }}>
      <line x1={pad} y1={size - pad} x2={size - 10} y2={size - pad} stroke="var(--color-border-strong)" />
      <line x1={pad} y1={size - pad} x2={pad} y2={10} stroke="var(--color-border-strong)" />
      {/* diagonal birth = death reference line */}
      <line x1={pad} y1={size - pad} x2={size - 10} y2={10} stroke="var(--color-border)" strokeDasharray="4 4" />

      <text x={size / 2} y={size - 6} fontSize={10} textAnchor="middle" fill="var(--color-text-muted)">
        Birth
      </text>
      <text x={10} y={size / 2} fontSize={10} textAnchor="middle" fill="var(--color-text-muted)" transform={`rotate(-90 10 ${size / 2})`}>
        Death
      </text>

      {points.map((p, i) => (
        <circle
          key={i}
          cx={scale(p.birth)}
          cy={size - scale(p.death)}
          r={p.dim === 0 ? 4 : 5.5}
          fill={p.dim === 0 ? 'var(--color-accent-strong)' : 'var(--color-risk-high)'}
          opacity={0.85}
        />
      ))}

      <g transform={`translate(${size - 130}, 16)`}>
        <circle cx={0} cy={0} r={4} fill="var(--color-accent-strong)" />
        <text x={8} y={3} fontSize={9} fill="var(--color-text-muted)">H0 — components</text>
        <circle cx={0} cy={14} r={5.5} fill="var(--color-risk-high)" />
        <text x={8} y={17} fontSize={9} fill="var(--color-text-muted)">H1 — loops</text>
      </g>
    </svg>
  )
}
