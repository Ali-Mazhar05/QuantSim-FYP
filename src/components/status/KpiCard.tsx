import clsx from 'clsx'
import type { LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'

export default function KpiCard({
  label,
  value,
  delta,
  deltaTone = 'neutral',
  icon: Icon,
  hint,
}: {
  label: string
  value: ReactNode
  delta?: string
  deltaTone?: 'positive' | 'negative' | 'neutral'
  icon?: LucideIcon
  hint?: string
}) {
  return (
    <div className="qs-panel rounded p-4">
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium uppercase tracking-wide text-[var(--color-text-muted)]">{label}</span>
        {Icon && <Icon size={15} className="text-[var(--color-text-muted)]" />}
      </div>
      <div className="mono mt-2 text-2xl font-semibold text-[var(--color-text-primary)]">{value}</div>
      <div className="mt-1 flex items-center gap-2">
        {delta && (
          <span
            className={clsx(
              'text-xs font-medium',
              deltaTone === 'positive' && 'text-[var(--color-risk-low)]',
              deltaTone === 'negative' && 'text-[var(--color-risk-severe)]',
              deltaTone === 'neutral' && 'text-[var(--color-text-muted)]',
            )}
          >
            {delta}
          </span>
        )}
        {hint && <span className="text-xs text-[var(--color-text-muted)]">{hint}</span>}
      </div>
    </div>
  )
}
