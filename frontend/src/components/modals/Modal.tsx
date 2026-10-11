import { X } from 'lucide-react'
import type { ReactNode } from 'react'
import { useEffect } from 'react'
import { createPortal } from 'react-dom'

export default function Modal({
  open,
  onClose,
  title,
  children,
  width = 'md',
}: {
  open: boolean
  onClose: () => void
  title: ReactNode
  children: ReactNode
  width?: 'sm' | 'md' | 'lg' | 'xl'
}) {
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null

  const widthClass = { sm: 'max-w-md', md: 'max-w-xl', lg: 'max-w-3xl', xl: 'max-w-5xl' }[width]

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={onClose}>
      <div
        className={`qs-panel qs-fade-in w-full ${widthClass} max-h-[85vh] overflow-y-auto rounded shadow-2xl`}
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex items-center justify-between border-b border-[var(--color-border)] px-5 py-3.5">
          <h3 className="text-sm font-semibold text-[var(--color-text-primary)]">{title}</h3>
          <button
            onClick={onClose}
            className="rounded p-1 text-[var(--color-text-muted)] hover:bg-black/5 hover:text-[var(--color-text-primary)]"
            aria-label="Close"
          >
            <X size={16} />
          </button>
        </header>
        <div className="p-5">{children}</div>
      </div>
    </div>,
    document.body,
  )
}
