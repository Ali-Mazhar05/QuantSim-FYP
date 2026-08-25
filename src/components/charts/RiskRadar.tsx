export default function RiskRadar({
  data,
  size = 260,
}: {
  data: { label: string; value: number }[]
  size?: number
}) {
  const cx = size / 2
  const cy = size / 2
  const r = size / 2 - 42
  const n = data.length
  const angle = (i: number) => (i / n) * Math.PI * 2 - Math.PI / 2
  const point = (i: number, value: number) => {
    const rr = (value / 100) * r
    return { x: cx + rr * Math.cos(angle(i)), y: cy + rr * Math.sin(angle(i)) }
  }

  const rings = [25, 50, 75, 100]
  const poly = data.map((d, i) => point(i, d.value))
  const polyStr = poly.map((p) => `${p.x},${p.y}`).join(' ')

  return (
    <svg viewBox={`0 0 ${size} ${size}`} className="w-full" style={{ maxWidth: size }}>
      {rings.map((ring) => (
        <polygon
          key={ring}
          points={data.map((_, i) => point(i, ring)).map((p) => `${p.x},${p.y}`).join(' ')}
          fill="none"
          stroke="var(--color-border)"
          strokeWidth={1}
        />
      ))}
      {data.map((_, i) => {
        const p = point(i, 100)
        return <line key={i} x1={cx} y1={cy} x2={p.x} y2={p.y} stroke="var(--color-border)" strokeWidth={1} />
      })}
      <polygon points={polyStr} fill="var(--color-accent)" opacity={0.22} stroke="var(--color-accent-strong)" strokeWidth={2} />
      {poly.map((p, i) => (
        <circle key={i} cx={p.x} cy={p.y} r={3.5} fill="var(--color-accent-strong)" />
      ))}
      {data.map((d, i) => {
        const p = point(i, 118)
        return (
          <text
            key={d.label}
            x={p.x}
            y={p.y}
            fontSize={10.5}
            textAnchor="middle"
            fill="var(--color-text-secondary)"
            fontWeight={600}
          >
            {d.label}
          </text>
        )
      })}
    </svg>
  )
}
