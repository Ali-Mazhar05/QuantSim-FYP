import clsx from 'clsx'

// Marks a feature that is shown in the POC to communicate the full product
// vision, but sits outside the core demo flow this build focuses on.
export default function ExtendedScopeBadge({ compact = false }: { compact?: boolean }) {
  return (
    <span
      className={clsx(
        'inline-flex shrink-0 items-center rounded border border-dashed border-[var(--color-border-strong)] font-semibold uppercase tracking-wide text-[var(--color-text-muted)]',
        compact ? 'px-1 py-0 text-[8px]' : 'px-1.5 py-0.5 text-[10px]',
      )}
    >
      Extended Scope
    </span>
  )
}
