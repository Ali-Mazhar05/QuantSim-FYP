import clsx from 'clsx'
import type { ReactNode } from 'react'

export default function Panel({
  title,
  subtitle,
  action,
  children,
  className,
  bodyClassName,
}: {
  title?: ReactNode
  subtitle?: ReactNode
  action?: ReactNode
  children: ReactNode
  className?: string
  bodyClassName?: string
}) {
  return (
    <section className={clsx('qs-panel rounded', className)}>
      {(title || action) && (
        <header className="flex items-center justify-between gap-3 border-b border-[var(--color-border)] px-4 py-3">
          <div>
            {title && <h3 className="text-sm font-semibold text-[var(--color-text-primary)]">{title}</h3>}
            {subtitle && <p className="mt-0.5 text-xs text-[var(--color-text-muted)]">{subtitle}</p>}
          </div>
          {action}
        </header>
      )}
      <div className={clsx('p-4', bodyClassName)}>{children}</div>
    </section>
  )
}
