export default function ProgressBar({ pct, tone = 'accent' }: { pct: number; tone?: 'accent' | 'risk' }) {
  const clamped = Math.max(0, Math.min(100, pct))
  return (
    <div className="h-2 w-full overflow-hidden rounded-full bg-[var(--color-bg-3)]">
      <div
        className="h-full rounded-full transition-[width] duration-300 ease-out"
        style={{
          width: `${clamped}%`,
          background:
            tone === 'accent'
              ? 'linear-gradient(90deg, var(--color-accent), var(--color-accent-strong))'
              : 'linear-gradient(90deg, var(--color-risk-elevated), var(--color-risk-high))',
        }}
      />
    </div>
  )
}
