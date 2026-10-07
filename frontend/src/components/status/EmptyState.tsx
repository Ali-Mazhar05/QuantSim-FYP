import type { LucideIcon } from 'lucide-react'
import { Inbox } from 'lucide-react'
import type { ReactNode } from 'react'

export default function EmptyState({
  icon: Icon = Inbox,
  title,
  description,
  action,
}: {
  icon?: LucideIcon
  title: string
  description?: string
  action?: ReactNode
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 rounded border border-dashed border-[var(--color-border)] py-16 text-center">
      <Icon size={28} className="text-[var(--color-text-muted)]" />
      <div className="text-sm font-medium text-[var(--color-text-secondary)]">{title}</div>
      {description && <div className="max-w-sm text-xs text-[var(--color-text-muted)]">{description}</div>}
      {action}
    </div>
  )
}
