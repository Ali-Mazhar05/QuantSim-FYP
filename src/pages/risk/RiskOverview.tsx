import { ArrowRight, Network as NetworkIcon, ShieldAlert, Sparkles } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import Button from '../../components/forms/Button'
import Panel from '../../components/layout/Panel'
import PageHeader from '../../components/layout/PageHeader'
import KpiCard from '../../components/status/KpiCard'
import RiskBadge, { scoreToLevel } from '../../components/status/RiskBadge'
import { useDemoStore } from '../../demo/demoState'
import { ML_PREDICTION, PORTFOLIO, STRESS_RESULT, TDA_ANALYSIS } from '../../services/mock/data'

const CARDS: { key: string; title: string; tagline: string; icon: LucideIcon; to: string; score: number }[] = [
  { key: 'stress', title: 'Stress Testing', tagline: 'What if disaster strikes?', icon: ShieldAlert, to: '/risk/stress-testing', score: STRESS_RESULT.score },
  { key: 'tda', title: 'TDA Analysis', tagline: 'Is market structure changing?', icon: NetworkIcon, to: '/risk/tda-analysis', score: TDA_ANALYSIS.score },
  { key: 'ml', title: 'ML Prediction', tagline: 'What does the data suggest?', icon: Sparkles, to: '/ml/predictions', score: ML_PREDICTION.score },
]

export default function RiskOverview() {
  const navigate = useNavigate()
  const advanceTo = useDemoStore((s) => s.advanceTo)
  const hasReached = useDemoStore((s) => s.hasReached)

  return (
    <div className="qs-fade-in flex flex-col gap-6">
      <PageHeader
        eyebrow="Step 7 of 8 — Risk"
        title="Portfolio Analysis"
        description={`${PORTFOLIO.name} · Simulation #1042`}
      />

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <KpiCard label="Portfolio Value" value={`$${PORTFOLIO.currentValue.toLocaleString()}`} />
        <KpiCard label="Return" value={`+${PORTFOLIO.returnPct}%`} deltaTone="positive" />
        <KpiCard label="Volatility" value={`${PORTFOLIO.volatilityPct}%`} />
        <KpiCard label="Max Drawdown" value={`${PORTFOLIO.maxDrawdownPct}%`} deltaTone="negative" />
      </div>

      <div>
        <h2 className="mb-3 text-sm font-semibold text-[var(--color-text-primary)]">Choose an Analysis</h2>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          {CARDS.map((c) => {
            const done = c.key === 'stress' ? hasReached('STRESS_COMPLETE') : c.key === 'tda' ? hasReached('TDA_COMPLETE') : hasReached('ML_COMPLETE')
            return (
              <button
                key={c.key}
                onClick={() => navigate(c.to)}
                className="qs-panel group flex flex-col items-start gap-3 rounded p-5 text-left transition-colors hover:border-[var(--color-accent-strong)]"
              >
                <div className="flex w-full items-center justify-between">
                  <c.icon size={20} className="text-[var(--color-accent-strong)]" />
                  {done && <RiskBadge level={scoreToLevel(c.score)} size="sm" />}
                </div>
                <div>
                  <div className="text-sm font-semibold text-[var(--color-text-primary)]">{c.title}</div>
                  <div className="mt-1 text-xs text-[var(--color-text-muted)]">"{c.tagline}"</div>
                </div>
                <span className="mt-auto flex items-center gap-1 text-xs font-medium text-[var(--color-accent-strong)] opacity-0 transition-opacity group-hover:opacity-100">
                  Open <ArrowRight size={12} />
                </span>
              </button>
            )
          })}
        </div>
      </div>

      <Panel title="Recommended Path" subtitle="Run all three risk lenses and generate the composite risk score.">
        <Button
          icon={ArrowRight}
          onClick={() => {
            advanceTo('RISK_ANALYSIS_READY')
            navigate('/risk/stress-testing')
          }}
        >
          Run Full Risk Analysis
        </Button>
      </Panel>
    </div>
  )
}
