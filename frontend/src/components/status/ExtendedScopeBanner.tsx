import { FlaskConical } from 'lucide-react'
import type { ReactNode } from 'react'

export default function ExtendedScopeBanner({ children }: { children: ReactNode }) {
  return (
    <div className="flex items-start gap-3 rounded border border-dashed border-[var(--color-border-strong)] bg-[var(--color-bg-2)] px-4 py-3">
      <FlaskConical size={16} className="mt-0.5 shrink-0 text-[var(--color-text-muted)]" />
      <p className="text-xs leading-relaxed text-[var(--color-text-secondary)]">
        <span className="mr-1 font-semibold uppercase tracking-wide text-[var(--color-text-primary)]">Extended Scope —</span>
        {children}
      </p>
    </div>
  )
}
