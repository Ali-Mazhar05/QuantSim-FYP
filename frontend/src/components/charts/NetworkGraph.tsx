import { useMemo } from 'react'

export default function NetworkGraph({
  assets,
  distanceMatrix,
  threshold,
  size = 320,
}: {
  assets: string[]
  distanceMatrix: number[][]
  threshold: number
  size?: number
}) {
  const nodes = useMemo(() => {
    const r = size / 2 - 40
    const cx = size / 2
    const cy = size / 2
    return assets.map((a, i) => {
      const angle = (i / assets.length) * Math.PI * 2 - Math.PI / 2
      return { symbol: a, x: cx + r * Math.cos(angle), y: cy + r * Math.sin(angle) }
    })
  }, [assets, size])

  const edges: { a: number; b: number; d: number }[] = []
  for (let i = 0; i < assets.length; i++) {
    for (let j = i + 1; j < assets.length; j++) {
      const d = distanceMatrix[i][j]
      if (d <= threshold) edges.push({ a: i, b: j, d })
    }
  }

  return (
    <svg viewBox={`0 0 ${size} ${size}`} className="mx-auto block w-full" style={{ maxWidth: size }}>
      {edges.map((e, i) => (
        <line
          key={i}
          x1={nodes[e.a].x}
          y1={nodes[e.a].y}
          x2={nodes[e.b].x}
          y2={nodes[e.b].y}
          stroke="var(--color-accent)"
          strokeWidth={Math.max(0.6, 2.2 - e.d * 1.8)}
          opacity={0.55}
        />
      ))}
      {nodes.map((n) => (
        <g key={n.symbol}>
          <circle cx={n.x} cy={n.y} r={16} fill="var(--color-bg-2)" stroke="var(--color-accent-strong)" strokeWidth={1.5} />
          <text x={n.x} y={n.y + 4} fontSize={9.5} textAnchor="middle" fill="var(--color-text-primary)" fontWeight={600}>
            {n.symbol}
          </text>
        </g>
      ))}
    </svg>
  )
}
