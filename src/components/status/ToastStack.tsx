import clsx from 'clsx'
import { CheckCircle2, Info, TriangleAlert, X } from 'lucide-react'
import { useNotifications } from '../../demo/notifications'

const ICONS = { info: Info, success: CheckCircle2, warning: TriangleAlert }

export default function ToastStack() {
  const { toasts, dismiss } = useNotifications()
  return (
    <div className="pointer-events-none fixed bottom-4 right-4 z-[60] flex flex-col gap-2">
      {toasts.map((t) => {
        const Icon = ICONS[t.tone]
        return (
          <div
            key={t.id}
            className={clsx(
              'qs-fade-in qs-panel pointer-events-auto flex w-80 items-start gap-2.5 rounded px-3.5 py-3 shadow-lg',
            )}
          >
            <Icon
              size={16}
              className={clsx(
                'mt-0.5 shrink-0',
                t.tone === 'info' && 'text-[var(--color-info)]',
                t.tone === 'success' && 'text-[var(--color-risk-low)]',
                t.tone === 'warning' && 'text-[var(--color-risk-elevated)]',
              )}
            />
            <p className="flex-1 text-xs leading-relaxed text-[var(--color-text-secondary)]">{t.title}</p>
            <button onClick={() => dismiss(t.id)} className="text-[var(--color-text-muted)] hover:text-[var(--color-text-primary)]">
              <X size={13} />
            </button>
          </div>
        )
      })}
    </div>
  )
}
