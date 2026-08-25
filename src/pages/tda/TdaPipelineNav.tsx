import clsx from 'clsx'
import { ChevronDown } from 'lucide-react'

export interface TdaStage {
  key: string
  label: string
}

export default function TdaPipelineNav({
  stages,
  activeIndex,
  unlockedIndex,
  onSelect,
}: {
  stages: TdaStage[]
  activeIndex: number
  unlockedIndex: number
  onSelect: (i: number) => void
}) {
  return (
    <div className="qs-panel flex flex-wrap items-center gap-1 rounded p-2">
      {stages.map((s, i) => (
        <div key={s.key} className="flex items-center">
          <button
            onClick={() => i <= unlockedIndex && onSelect(i)}
            disabled={i > unlockedIndex}
            className={clsx(
              'rounded px-2.5 py-1.5 text-xs font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-35',
              i === activeIndex
                ? 'bg-[var(--color-accent)] text-white'
                : i <= unlockedIndex
                  ? 'text-[var(--color-text-secondary)] hover:bg-white/5 hover:text-[var(--color-text-primary)]'
                  : 'text-[var(--color-text-muted)]',
            )}
          >
            {s.label}
          </button>
          {i < stages.length - 1 && <ChevronDown size={12} className="mx-0.5 -rotate-90 text-[var(--color-text-muted)]" />}
        </div>
      ))}
    </div>
  )
}
