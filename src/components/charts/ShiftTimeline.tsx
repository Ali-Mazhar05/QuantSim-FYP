export default function ShiftTimeline({
  shiftLabel,
  shiftPositionPct = 68,
}: {
  shiftLabel: string
  shiftPositionPct?: number
}) {
  return (
    <div className="relative pt-2 pb-8">
      <div className="h-px w-full bg-[var(--color-border-strong)]" />
      <span className="absolute left-0 -top-4 text-[10px] uppercase tracking-wide text-[var(--color-text-muted)]">Historical</span>
      <span className="absolute right-0 -top-4 text-[10px] uppercase tracking-wide text-[var(--color-text-muted)]">Current</span>
      <div className="absolute top-0 -translate-x-1/2" style={{ left: `${shiftPositionPct}%` }}>
        <div className="h-2.5 w-2.5 -translate-y-1/2 rounded-full bg-[var(--color-risk-high)] ring-4 ring-[var(--color-risk-high)]/20" />
        <div className="mt-1.5 whitespace-nowrap text-[10px] font-semibold text-[var(--color-risk-high)]">↑ {shiftLabel}</div>
      </div>
    </div>
  )
}
