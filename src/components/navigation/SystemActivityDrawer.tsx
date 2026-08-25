import clsx from 'clsx'
import { Radio, X } from 'lucide-react'
import { useDemoStore } from '../../demo/demoState'
import { SYSTEM_EVENTS } from '../../services/mock/data'

export default function SystemActivityDrawer() {
  const open = useDemoStore((s) => s.systemActivityOpen)
  const toggle = useDemoStore((s) => s.toggleSystemActivity)
  const flowStep = useDemoStore((s) => s.flowStep)

  const reachedCount = flowStep === 'IDLE' ? 0 : SYSTEM_EVENTS.length

  if (!open) return null

  return (
    <div className="fixed inset-0 z-40 flex justify-end" onClick={toggle}>
      <div className="absolute inset-0 bg-black/50" />
      <div
        className="qs-slide-in qs-panel relative flex h-full w-96 flex-col shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex items-center justify-between border-b border-[var(--color-border)] px-4 py-3.5">
          <div className="flex items-center gap-2">
            <Radio size={15} className="text-[var(--color-accent-strong)]" />
            <h3 className="text-sm font-semibold">System Activity</h3>
          </div>
          <button onClick={toggle} className="text-[var(--color-text-muted)] hover:text-[var(--color-text-primary)]">
            <X size={16} />
          </button>
        </header>
        <p className="border-b border-[var(--color-border)] px-4 py-2.5 text-xs text-[var(--color-text-muted)]">
          Illustrative event stream representing the asynchronous, event-driven backbone of the full QuantSim
          architecture.
        </p>
        <div className="qs-scrollbar-thin flex-1 overflow-y-auto px-4 py-4">
          <ol className="relative flex flex-col gap-0">
            {SYSTEM_EVENTS.map((e, i) => {
              const reached = i < reachedCount
              return (
                <li key={e.id} className="relative flex gap-3 pb-6 last:pb-0">
                  {i < SYSTEM_EVENTS.length - 1 && (
                    <span
                      className={clsx(
                        'absolute left-[7px] top-4 h-full w-px',
                        reached ? 'bg-[var(--color-accent)]/50' : 'bg-[var(--color-border)]',
                      )}
                    />
                  )}
                  <span
                    className={clsx(
                      'z-10 mt-1 h-3.5 w-3.5 shrink-0 rounded-full border-2',
                      reached
                        ? 'border-[var(--color-accent)] bg-[var(--color-accent)]/30'
                        : 'border-[var(--color-border-strong)] bg-[var(--color-bg-2)]',
                    )}
                  />
                  <div>
                    <div
                      className={clsx(
                        'mono text-xs font-semibold',
                        reached ? 'text-[var(--color-accent-strong)]' : 'text-[var(--color-text-muted)]',
                      )}
                    >
                      {e.type}
                    </div>
                    <div className="mt-0.5 text-xs text-[var(--color-text-secondary)]">{e.detail}</div>
                    <div className="mono mt-0.5 text-[10px] text-[var(--color-text-muted)]">{e.timestamp}</div>
                  </div>
                </li>
              )
            })}
          </ol>
        </div>
      </div>
    </div>
  )
}
