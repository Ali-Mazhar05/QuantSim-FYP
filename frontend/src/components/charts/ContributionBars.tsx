export default function ContributionBars({
  data,
  color = 'var(--color-accent)',
  suffix = '%',
}: {
  data: { label: string; value: number }[]
  color?: string
  suffix?: string
}) {
  const max = Math.max(...data.map((d) => d.value), 1)
  return (
    <div className="flex flex-col gap-2.5">
      {data.map((d) => (
        <div key={d.label} className="flex items-center gap-3">
          <span className="w-20 shrink-0 text-xs font-medium text-[var(--color-text-secondary)]">{d.label}</span>
          <div className="h-3.5 flex-1 overflow-hidden rounded bg-[var(--color-bg-3)]">
            <div
              className="h-full rounded"
              style={{ width: `${(d.value / max) * 100}%`, background: color }}
            />
          </div>
          <span className="mono w-12 shrink-0 text-right text-xs text-[var(--color-text-primary)]">
            {d.value}
            {suffix}
          </span>
        </div>
      ))}
    </div>
  )
}
