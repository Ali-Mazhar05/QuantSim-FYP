import { useMemo } from 'react'
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { generateDrawdownSeries, generateEquityCurve } from '../../services/mock/generators'

export default function DrawdownChart({ height = 180 }: { height?: number }) {
  const data = useMemo(() => {
    const equity = generateEquityCurve({ seed: 909, days: 60, start: 1_000_000, drift: 0.0834, vol: 0.182 })
    return generateDrawdownSeries(equity)
  }, [])
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
        <defs>
          <linearGradient id="ddFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--color-risk-severe)" stopOpacity={0} />
            <stop offset="100%" stopColor="var(--color-risk-severe)" stopOpacity={0.35} />
          </linearGradient>
        </defs>
        <CartesianGrid stroke="var(--color-border)" vertical={false} />
        <XAxis dataKey="day" tick={{ fontSize: 10, fill: 'var(--color-text-muted)' }} tickFormatter={(v) => `D${v}`} />
        <YAxis tick={{ fontSize: 10, fill: 'var(--color-text-muted)' }} tickFormatter={(v) => `${v}%`} width={44} />
        <Tooltip
          contentStyle={{ background: 'var(--color-bg-2)', border: '1px solid var(--color-border)', fontSize: 12 }}
          formatter={(v) => [`${Number(v).toFixed(2)}%`, 'Drawdown']}
          labelFormatter={(v) => `Day ${v}`}
        />
        <Area type="monotone" dataKey="drawdown" stroke="var(--color-risk-high)" strokeWidth={1.75} fill="url(#ddFill)" />
      </AreaChart>
    </ResponsiveContainer>
  )
}
