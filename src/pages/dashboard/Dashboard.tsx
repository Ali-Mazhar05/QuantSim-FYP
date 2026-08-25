import { AlertTriangle, ArrowUpRight, Play, TrendingDown, TrendingUp } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import Button from '../../components/forms/Button'
import EquityCurve from '../../components/charts/EquityCurve'
import Panel from '../../components/layout/Panel'
import KpiCard from '../../components/status/KpiCard'
import RiskBadge from '../../components/status/RiskBadge'
import StatusPill from '../../components/status/StatusPill'
import { useDemoStore } from '../../demo/demoState'
import { ALERT, COMPOSITE_RISK, ML_PREDICTION, PORTFOLIO, STRESS_RESULT, TDA_ANALYSIS } from '../../services/mock/data'
import RiskEngineCard from './RiskEngineCard'

export default function Dashboard() {
  const navigate = useNavigate()
  const role = useDemoStore((s) => s.role)
  const flowStep = useDemoStore((s) => s.flowStep)
  const hasReached = useDemoStore((s) => s.hasReached)
  const alertActive = useDemoStore((s) => s.alertActive)

  const analysisComplete = hasReached('COMPOSITE_RISK_READY')
  const hour = 16
  const greeting = hour < 12 ? 'Good morning' : hour < 18 ? 'Good afternoon' : 'Good evening'

  return (
    <div className="qs-fade-in flex flex-col gap-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-[var(--color-text-primary)]">
            {greeting}, {role}
          </h1>
          <div className="mt-2 flex flex-wrap gap-x-8 gap-y-1.5 text-sm">
            <div>
              <span className="text-[var(--color-text-muted)]">Market environment: </span>
              <span className="font-medium text-[var(--color-text-primary)]">US Equities — Synthetic Replay</span>
            </div>
            <div>
              <span className="text-[var(--color-text-muted)]">Simulation: </span>
              <span className="font-medium text-[var(--color-text-primary)]">Momentum Strategy — Run #1042</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="text-[var(--color-text-muted)]">Risk status:</span>
              <RiskBadge level={analysisComplete ? COMPOSITE_RISK.level : 'MODERATE'} size="sm" />
            </div>
          </div>
        </div>
        <Button icon={Play} onClick={() => navigate('/market/environments/new')}>
          Run New Analysis
        </Button>
      </div>

      {alertActive && (
        <button
          onClick={() => navigate('/alerts')}
          className="qs-fade-in flex items-center gap-3 rounded border border-[var(--color-risk-high)]/40 bg-[var(--color-risk-high)]/10 px-4 py-3 text-left hover:bg-[var(--color-risk-high)]/15"
        >
          <AlertTriangle size={18} className="shrink-0 text-[var(--color-risk-high)]" />
          <div className="flex-1">
            <div className="text-sm font-semibold text-[var(--color-risk-high)]">1 active high-risk alert</div>
            <div className="text-xs text-[var(--color-text-secondary)]">{ALERT.message} — {ALERT.detail}</div>
          </div>
          <ArrowUpRight size={15} className="text-[var(--color-risk-high)]" />
        </button>
      )}

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-7">
        <KpiCard label="Portfolio Value" value={`$${PORTFOLIO.currentValue.toLocaleString()}`} delta={`+${PORTFOLIO.returnPct}%`} deltaTone="positive" icon={TrendingUp} />
        <KpiCard label="Daily P&L" value="+$4,218" delta="+0.39%" deltaTone="positive" icon={TrendingUp} />
        <KpiCard label="Volatility" value={`${PORTFOLIO.volatilityPct}%`} hint="annualized" icon={TrendingDown} />
        <KpiCard label="VaR (95%)" value={`${STRESS_RESULT.var}%`} deltaTone="negative" icon={TrendingDown} />
        <KpiCard label="CVaR (95%)" value={`${STRESS_RESULT.cvar}%`} deltaTone="negative" icon={TrendingDown} />
        <KpiCard label="Max Drawdown" value={`${PORTFOLIO.maxDrawdownPct}%`} deltaTone="negative" icon={TrendingDown} />
        <KpiCard
          label="Composite Risk"
          value={analysisComplete ? COMPOSITE_RISK.compositeScore : '—'}
          hint={analysisComplete ? COMPOSITE_RISK.level : 'Not yet run'}
        />
      </div>

      <div className="grid grid-cols-1 gap-5 xl:grid-cols-[1.4fr_1fr]">
        <Panel title="Portfolio Equity Curve" subtitle="Momentum Strategy — Run #1042 · last 60 sessions">
          <EquityCurve />
        </Panel>
        <RiskEngineCard
          stress={analysisComplete ? STRESS_RESULT.score : 0}
          tda={analysisComplete ? TDA_ANALYSIS.score : 0}
          ml={analysisComplete ? ML_PREDICTION.score : 0}
          composite={analysisComplete ? COMPOSITE_RISK.compositeScore : 0}
          ready={analysisComplete}
        />
      </div>

      <div className="grid grid-cols-1 gap-5 md:grid-cols-2">
        <Panel title="Latest Analysis" subtitle="Simulation #1042">
          {flowStep === 'IDLE' ? (
            <p className="text-sm text-[var(--color-text-muted)]">No active run. Start a new analysis to populate this panel.</p>
          ) : (
            <dl className="grid grid-cols-2 gap-3 text-sm">
              <div>
                <dt className="text-xs text-[var(--color-text-muted)]">Status</dt>
                <dd className="mt-0.5">
                  <StatusPill tone={analysisComplete ? 'success' : 'info'}>
                    {analysisComplete ? 'Completed' : 'In progress'}
                  </StatusPill>
                </dd>
              </div>
              <div>
                <dt className="text-xs text-[var(--color-text-muted)]">Completed</dt>
                <dd className="mono mt-0.5 text-[var(--color-text-primary)]">{analysisComplete ? '16:21' : '—'}</dd>
              </div>
              <div>
                <dt className="text-xs text-[var(--color-text-muted)]">Strategy</dt>
                <dd className="mt-0.5 text-[var(--color-text-primary)]">Momentum Strategy</dd>
              </div>
              <div>
                <dt className="text-xs text-[var(--color-text-muted)]">Universe</dt>
                <dd className="mt-0.5 text-[var(--color-text-primary)]">US Technology Basket</dd>
              </div>
            </dl>
          )}
        </Panel>
        <Panel title="Risk Breakdown" subtitle={analysisComplete ? undefined : 'Available once risk analysis completes'}>
          {analysisComplete ? (
            <div className="flex flex-col gap-3">
              {[
                { label: 'Stress Testing', score: STRESS_RESULT.score, level: STRESS_RESULT.level },
                { label: 'TDA', score: TDA_ANALYSIS.score, level: TDA_ANALYSIS.level },
                { label: 'ML', score: ML_PREDICTION.score, level: ML_PREDICTION.level },
              ].map((r) => (
                <div key={r.label} className="flex items-center justify-between">
                  <span className="text-sm text-[var(--color-text-secondary)]">{r.label}</span>
                  <div className="flex items-center gap-2">
                    <span className="mono text-sm text-[var(--color-text-primary)]">{r.score}</span>
                    <RiskBadge level={r.level} size="sm" />
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-[var(--color-text-muted)]">
              Run stress testing, TDA, and ML prediction to populate the composite risk breakdown.
            </p>
          )}
        </Panel>
      </div>
    </div>
  )
}
