import clsx from 'clsx'
import { Play, RotateCcw, Square } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { DEMO_STAGES, useDemoStore } from '../../demo/demoState'
import { runFullDemo, stopFullDemo } from '../../demo/demoFlows'
import { useNotifications } from '../../demo/notifications'

export default function DemoControlBar() {
  const navigate = useNavigate()
  const flowStep = useDemoStore((s) => s.flowStep)
  const hasReached = useDemoStore((s) => s.hasReached)
  const running = useDemoStore((s) => s.runningFullDemo)
  const resetDemo = useDemoStore((s) => s.resetDemo)
  const push = useNotifications((s) => s.push)

  return (
    <div className="flex h-10 shrink-0 items-center justify-between border-b border-[var(--color-border)] bg-[var(--color-bg-2)] px-4">
      <div className="flex items-center gap-2.5 overflow-x-auto">
        <span className="mr-1 whitespace-nowrap text-[10px] font-semibold uppercase tracking-wide text-[var(--color-text-muted)]">
          Demo Progress
        </span>
        {DEMO_STAGES.map((stage) => {
          const active = hasReached(stage.step)
          return (
            <button
              key={stage.key}
              onClick={() => navigate(stage.path)}
              className="flex items-center gap-1.5 whitespace-nowrap text-xs font-medium"
              title={`Go to ${stage.label}`}
            >
              <span
                className={clsx(
                  'h-2 w-2 rounded-full',
                  active ? 'bg-[var(--color-accent-strong)]' : 'bg-[var(--color-border-strong)]',
                )}
              />
              <span className={active ? 'text-[var(--color-text-primary)]' : 'text-[var(--color-text-muted)]'}>
                {stage.label}
              </span>
            </button>
          )
        })}
      </div>
      <div className="flex shrink-0 items-center gap-2 pl-3">
        {flowStep !== 'IDLE' && (
          <button
            onClick={() => {
              stopFullDemo()
              resetDemo()
              navigate('/dashboard')
              push('Demo reset', 'info')
            }}
            className="flex items-center gap-1.5 rounded px-2 py-1 text-xs font-medium text-[var(--color-text-secondary)] hover:text-[var(--color-text-primary)]"
          >
            <RotateCcw size={12} />
            Reset Demo
          </button>
        )}
        {running ? (
          <button
            onClick={() => {
              stopFullDemo()
              push('Full demo paused', 'info')
            }}
            className="flex items-center gap-1.5 rounded bg-[var(--color-risk-severe)] px-2.5 py-1 text-xs font-semibold text-white hover:brightness-110"
          >
            <Square size={12} />
            Stop
          </button>
        ) : (
          <button
            onClick={() => runFullDemo(navigate)}
            className="flex items-center gap-1.5 rounded bg-[var(--color-accent)] px-2.5 py-1 text-xs font-semibold text-black hover:bg-[var(--color-accent-strong)]"
          >
            <Play size={12} />
            Run Full Demo
          </button>
        )}
      </div>
    </div>
  )
}
