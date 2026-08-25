import { HelpCircle, X } from 'lucide-react'
import { useState } from 'react'
import type { ReactNode } from 'react'

export default function ExplainThis({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="relative inline-block">
      <button
        onClick={() => setOpen((v) => !v)}
        className="inline-flex items-center gap-1 rounded border border-[var(--color-border-strong)] px-2 py-1 text-xs font-medium text-[var(--color-text-secondary)] hover:border-[var(--color-accent)] hover:text-[var(--color-accent-strong)]"
      >
        <HelpCircle size={12} />
        What is this?
      </button>
      {open && (
        <div className="qs-fade-in qs-panel absolute right-0 top-full z-20 mt-2 w-72 rounded p-4 shadow-xl">
          <button
            onClick={() => setOpen(false)}
            className="absolute right-2 top-2 text-[var(--color-text-muted)] hover:text-[var(--color-text-primary)]"
          >
            <X size={13} />
          </button>
          <div className="pr-4 text-xs leading-relaxed text-[var(--color-text-secondary)]">{children}</div>
          <button
            onClick={() => setOpen(false)}
            className="mt-3 rounded bg-[var(--color-accent)] px-3 py-1 text-xs font-medium text-black hover:bg-[var(--color-accent-strong)]"
          >
            Got it
          </button>
        </div>
      )}
    </div>
  )
}
