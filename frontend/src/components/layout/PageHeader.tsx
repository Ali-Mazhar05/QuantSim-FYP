import { ChevronRight } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'

export default function PageHeader({
  eyebrow,
  title,
  description,
  breadcrumbs,
  action,
}: {
  eyebrow?: string
  title: ReactNode
  description?: ReactNode
  breadcrumbs?: { label: string; to?: string }[]
  action?: ReactNode
}) {
  return (
    <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
      <div>
        {breadcrumbs && (
          <div className="mb-2 flex items-center gap-1 text-xs text-[var(--color-text-muted)]">
            {breadcrumbs.map((b, i) => (
              <span key={b.label} className="flex items-center gap-1">
                {i > 0 && <ChevronRight size={12} />}
                {b.to ? (
                  <Link to={b.to} className="hover:text-[var(--color-accent-strong)]">
                    {b.label}
                  </Link>
                ) : (
                  <span className="text-[var(--color-text-secondary)]">{b.label}</span>
                )}
              </span>
            ))}
          </div>
        )}
        {eyebrow && (
          <div className="mb-1 text-xs font-semibold uppercase tracking-wider text-[var(--color-accent-strong)]">
            {eyebrow}
          </div>
        )}
        <h1 className="text-xl font-semibold text-[var(--color-text-primary)]">{title}</h1>
        {description && <p className="mt-1 max-w-2xl text-sm text-[var(--color-text-secondary)]">{description}</p>}
      </div>
      {action && <div className="flex shrink-0 items-center gap-2">{action}</div>}
    </div>
  )
}
