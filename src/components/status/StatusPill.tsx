import clsx from 'clsx'
import type { ReactNode } from 'react'

type Tone = 'neutral' | 'success' | 'warning' | 'danger' | 'info'

// Borders run at /70 rather than /40 so the pill still reads as a bounded
// control against white, and `info` is blue instead of the brand teal so it
// cannot be mistaken for `success` at a glance.
const TONE_STYLES: Record<Tone, string> = {
  neutral: 'text-[var(--color-text-secondary)] border-[var(--color-border-control)] bg-black/[0.03]',
  success: 'text-[var(--color-risk-low)] border-[var(--color-risk-low)]/70 bg-[var(--color-risk-low)]/10',
  warning: 'text-[var(--color-risk-elevated)] border-[var(--color-risk-elevated)]/70 bg-[var(--color-risk-elevated)]/10',
  danger: 'text-[var(--color-risk-severe)] border-[var(--color-risk-severe)]/70 bg-[var(--color-risk-severe)]/10',
  info: 'text-[var(--color-info)] border-[var(--color-info)]/70 bg-[var(--color-info)]/10',
}

export default function StatusPill({
  tone = 'neutral',
  children,
  dot = false,
}: {
  tone?: Tone
  children: ReactNode
  dot?: boolean
}) {
  return (
    <span
      className={clsx(
        'inline-flex items-center gap-1.5 rounded border px-2 py-0.5 text-xs font-medium',
        TONE_STYLES[tone],
      )}
    >
      {dot && <span className={clsx('h-1.5 w-1.5 rounded-full', tone === 'success' && 'qs-live-dot')} style={{ background: 'currentColor' }} />}
      {children}
    </span>
  )
}
