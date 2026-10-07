import { useMemo } from 'react'
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { generateEquityCurve } from '../../services/mock/generators'
import { seriesOutcomeColor } from '../../utils/outcomeColor'

export default function EquityCurve({ height = 220 }: { height?: number }) {
  const data = useMemo(
    () => generateEquityCurve({ seed: 909, days: 60, start: 1_000_000, drift: 0.0834, vol: 0.182 }),
    [],
  )
  const color = useMemo(() => seriesOutcomeColor(data.map((d) => d.value)), [data])

  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
        <defs>
          <linearGradient id="equityFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity={0.32} />
            <stop offset="100%" stopColor={color} stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid stroke="var(--color-border)" vertical={false} />
        <XAxis dataKey="day" tick={{ fontSize: 10, fill: 'var(--color-text-muted)' }} tickFormatter={(v) => `D${v}`} />
        <YAxis
          tick={{ fontSize: 10, fill: 'var(--color-text-muted)' }}
          tickFormatter={(v) => `$${(v / 1000).toFixed(0)}k`}
          width={54}
          domain={['dataMin - 20000', 'dataMax + 20000']}
        />
        <Tooltip
          contentStyle={{ background: 'var(--color-bg-2)', border: '1px solid var(--color-border)', fontSize: 12 }}
          labelFormatter={(v) => `Day ${v}`}
          formatter={(v) => [`$${Number(v).toLocaleString(undefined, { maximumFractionDigits: 0 })}`, 'Portfolio value']}
        />
        <Area type="monotone" dataKey="value" stroke={color} strokeWidth={2} fill="url(#equityFill)" />
      </AreaChart>
    </ResponsiveContainer>
  )
}
