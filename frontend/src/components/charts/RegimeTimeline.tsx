import clsx from 'clsx'

const REGIME_COLOR: Record<string, string> = {
  Calm: 'var(--color-risk-low)',
  Transition: 'var(--color-risk-moderate)',
  Stress: 'var(--color-risk-high)',
}

export default function RegimeTimeline({ regimes }: { regimes: string[] }) {
  return (
    <div className="flex items-center gap-1">
      {regimes.map((r, i) => (
        <div key={i} className="flex flex-1 flex-col items-center gap-1.5">
          <div
            className={clsx('h-2 w-full rounded-full', i === regimes.length - 1 && 'ring-2 ring-offset-2 ring-offset-[var(--color-bg-1)]')}
            style={{ background: REGIME_COLOR[r], ...(i === regimes.length - 1 ? { boxShadow: `0 0 0 2px ${REGIME_COLOR[r]}40` } : {}) }}
          />
          <span className="text-[10px] font-semibold uppercase tracking-wide" style={{ color: REGIME_COLOR[r] }}>
            {r}
          </span>
        </div>
      ))}
    </div>
  )
}
