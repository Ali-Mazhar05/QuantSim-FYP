import clsx from 'clsx'
import { Check } from 'lucide-react'

export default function StepIndicator({
  steps,
  activeIndex,
}: {
  steps: string[]
  activeIndex: number
}) {
  return (
    <ol className="flex items-center gap-2">
      {steps.map((label, i) => {
        const done = i < activeIndex
        const active = i === activeIndex
        return (
          <li key={label} className="flex items-center gap-2">
            <div
              className={clsx(
                'flex h-6 w-6 shrink-0 items-center justify-center rounded-full border text-[11px] font-semibold',
                done && 'border-[var(--color-accent)] bg-[var(--color-accent)] text-black',
                active && 'border-[var(--color-accent-strong)] text-[var(--color-accent-strong)]',
                !done && !active && 'border-[var(--color-border-strong)] text-[var(--color-text-muted)]',
              )}
            >
              {done ? <Check size={13} /> : i + 1}
            </div>
            <span
              className={clsx(
                'text-xs font-medium',
                (done || active) ? 'text-[var(--color-text-primary)]' : 'text-[var(--color-text-muted)]',
              )}
            >
              {label}
            </span>
            {i < steps.length - 1 && <div className="mx-1 h-px w-6 bg-[var(--color-border-strong)]" />}
          </li>
        )
      })}
    </ol>
  )
}
