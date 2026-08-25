import clsx from 'clsx'
import type { RiskLevel } from '../../types'

const LEVEL_STYLES: Record<RiskLevel, string> = {
  LOW: 'text-[var(--color-risk-low)] border-[var(--color-risk-low)]/70 bg-[var(--color-risk-low)]/10',
  MODERATE: 'text-[var(--color-risk-moderate)] border-[var(--color-risk-moderate)]/70 bg-[var(--color-risk-moderate)]/10',
  ELEVATED: 'text-[var(--color-risk-elevated)] border-[var(--color-risk-elevated)]/70 bg-[var(--color-risk-elevated)]/10',
  HIGH: 'text-[var(--color-risk-high)] border-[var(--color-risk-high)]/70 bg-[var(--color-risk-high)]/10',
  SEVERE: 'text-[var(--color-risk-severe)] border-[var(--color-risk-severe)]/70 bg-[var(--color-risk-severe)]/10',
}

export function riskColor(level: RiskLevel) {
  return {
    LOW: 'var(--color-risk-low)',
    MODERATE: 'var(--color-risk-moderate)',
    ELEVATED: 'var(--color-risk-elevated)',
    HIGH: 'var(--color-risk-high)',
    SEVERE: 'var(--color-risk-severe)',
  }[level]
}

export function scoreToLevel(score: number): RiskLevel {
  if (score >= 85) return 'SEVERE'
  if (score >= 70) return 'HIGH'
  if (score >= 50) return 'ELEVATED'
  if (score >= 30) return 'MODERATE'
  return 'LOW'
}

export default function RiskBadge({ level, size = 'md' }: { level: RiskLevel; size?: 'sm' | 'md' | 'lg' }) {
  return (
    <span
      className={clsx(
        'inline-flex items-center gap-1.5 rounded border font-semibold uppercase tracking-wide',
        LEVEL_STYLES[level],
        size === 'sm' && 'px-1.5 py-0.5 text-[10px]',
        size === 'md' && 'px-2 py-1 text-xs',
        size === 'lg' && 'px-3 py-1.5 text-sm',
      )}
    >
      <span className="h-1.5 w-1.5 rounded-full" style={{ background: riskColor(level) }} />
      {level}
    </span>
  )
}
