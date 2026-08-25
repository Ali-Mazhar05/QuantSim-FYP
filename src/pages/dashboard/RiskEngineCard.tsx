import clsx from 'clsx'
import { ArrowRight, ShieldAlert, Sparkles, Network as NetworkIcon } from 'lucide-react'
import { Link } from 'react-router-dom'
import RiskBadge, { scoreToLevel } from '../../components/status/RiskBadge'

const LENSES = [
  { key: 'stress', label: 'Stress', icon: ShieldAlert, to: '/risk/stress-testing' },
  { key: 'tda', label: 'TDA', icon: NetworkIcon, to: '/risk/tda-analysis' },
  { key: 'ml', label: 'ML', icon: Sparkles, to: '/ml/predictions' },
]

export default function RiskEngineCard({
  stress,
  tda,
  ml,
  composite,
  ready,
}: {
  stress: number
  tda: number
  ml: number
  composite: number
  ready: boolean
}) {
  const scores = { stress, tda, ml }
  return (
    <div className="qs-panel rounded p-5">
      <div className="mb-4 text-center text-xs font-semibold uppercase tracking-[0.2em] text-[var(--color-text-muted)]">
        QuantSim Risk Engine
      </div>
      <div className="grid grid-cols-3 gap-3">
        {LENSES.map((lens) => {
          const score = scores[lens.key as keyof typeof scores]
          const level = scoreToLevel(score)
          return (
            <Link
              key={lens.key}
              to={ready ? lens.to : '#'}
              className={clsx(
                'qs-panel-2 flex flex-col items-center gap-2 rounded p-4 text-center transition-colors',
                ready && 'hover:border-[var(--color-accent)]',
                !ready && 'pointer-events-none opacity-50',
              )}
            >
              <lens.icon size={16} className="text-[var(--color-text-muted)]" />
              <span className="text-[11px] font-semibold uppercase tracking-wide text-[var(--color-text-muted)]">
                {lens.label}
              </span>
              <span className="mono text-2xl font-semibold text-[var(--color-text-primary)]">{score}<span className="text-sm text-[var(--color-text-muted)]">/100</span></span>
              <RiskBadge level={level} size="sm" />
            </Link>
          )
        })}
      </div>

      <div className="my-4 flex flex-col items-center gap-1 text-[var(--color-text-muted)]">
        <div className="h-6 w-px bg-[var(--color-border-strong)]" />
        <ArrowRight size={14} className="rotate-90" />
      </div>

      <Link
        to={ready ? '/risk/composite' : '#'}
        className={clsx(
          'qs-panel-2 flex flex-col items-center gap-1.5 rounded p-5 text-center transition-colors',
          ready && 'hover:border-[var(--color-accent)]',
          !ready && 'pointer-events-none opacity-50',
        )}
      >
        <span className="text-[11px] font-semibold uppercase tracking-wide text-[var(--color-text-muted)]">Composite Risk</span>
        <span className="mono text-4xl font-bold text-[var(--color-text-primary)]">{composite}<span className="text-lg text-[var(--color-text-muted)]">/100</span></span>
        <RiskBadge level={scoreToLevel(composite)} />
      </Link>
    </div>
  )
}
