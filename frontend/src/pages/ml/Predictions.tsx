import clsx from 'clsx'
import { ArrowLeft, ArrowRight } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import ContributionBars from '../../components/charts/ContributionBars'
import RegimeTimeline from '../../components/charts/RegimeTimeline'
import Button from '../../components/forms/Button'
import Panel from '../../components/layout/Panel'
import PageHeader from '../../components/layout/PageHeader'
import RiskBadge from '../../components/status/RiskBadge'
import StatusPill from '../../components/status/StatusPill'
import { useDemoStore } from '../../demo/demoState'
import { useRiskAnalysis } from '../../demo/useRiskAnalysis'
import { ML_PREDICTION } from '../../services/mock/data'
import { RISK_MODULES } from '../../services/mock/riskModules'

const PROCESSING_STEPS = [
  'Loading feature matrix',
  'Scoring volatility model',
  'Estimating drawdown probability',
  'Classifying market regime',
]

export default function Predictions() {
  const navigate = useNavigate()
  const startRiskModule = useDemoStore((s) => s.startRiskModule)
  const completeRiskModule = useDemoStore((s) => s.completeRiskModule)
  const { status, nextPending } = useRiskAnalysis()

  const [phase, setPhase] = useState<'select' | 'processing' | 'complete'>(
    status.ml === 'complete' ? 'complete' : 'select',
  )
  const [step, setStep] = useState(0)

  useEffect(() => {
    if (phase !== 'processing') return
    if (step >= PROCESSING_STEPS.length) {
      const t = setTimeout(() => {
        setPhase('complete')
        completeRiskModule('ml')
      }, 350)
      return () => clearTimeout(t)
    }
    const t = setTimeout(() => setStep((s) => s + 1), 500)
    return () => clearTimeout(t)
  }, [phase, step, completeRiskModule])

  return (
    <div className="qs-fade-in flex flex-col gap-6">
      <PageHeader
        title="Machine Learning Intelligence"
        description={`${ML_PREDICTION.modelName} ${ML_PREDICTION.modelVersion}`}
        breadcrumbs={[{ label: 'Risk', to: '/risk/overview' }, { label: 'ML Prediction' }]}
        action={
          phase === 'complete' ? (
            <RiskBadge level={ML_PREDICTION.level} />
          ) : (
            <StatusPill>Not run</StatusPill>
          )
        }
      />

      {phase === 'select' && (
        <Panel title="Model" subtitle="Gradient-boosted risk model trained on the simulated portfolio history">
          <p className="text-sm text-[var(--color-text-secondary)]">
            The model forecasts short-horizon volatility, drawdown probability, and the prevailing market regime
            for the portfolio. Run it to add the ML lens to your risk analysis.
          </p>
          <div className="mt-4">
            <Button
              onClick={() => {
                startRiskModule('ml')
                setPhase('processing')
                setStep(0)
              }}
            >
              Run ML Prediction
            </Button>
          </div>
        </Panel>
      )}

      {phase === 'processing' && (
        <Panel title="Processing">
          <div className="flex flex-col gap-2.5">
            {PROCESSING_STEPS.map((s, i) => (
              <div
                key={s}
                className={clsx(
                  'flex items-center gap-2.5 text-sm',
                  i < step
                    ? 'text-[var(--color-text-primary)]'
                    : i === step
                      ? 'text-[var(--color-accent-strong)]'
                      : 'text-[var(--color-text-muted)]',
                )}
              >
                <span
                  className={clsx(
                    'h-2 w-2 rounded-full',
                    i < step
                      ? 'bg-[var(--color-risk-low)]'
                      : i === step
                        ? 'bg-[var(--color-accent-strong)] qs-live-dot'
                        : 'bg-[var(--color-border-strong)]',
                  )}
                />
                {s}
              </div>
            ))}
          </div>
        </Panel>
      )}

      {phase === 'complete' && (
        <>
          <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
            <Stat label="Volatility Forecast" value={`${ML_PREDICTION.volatilityForecastPct}%`} />
            <Stat label="Drawdown Probability" value={`${ML_PREDICTION.drawdownProbabilityPct}%`} tone="negative" />
            <Stat label="Market Regime" value={ML_PREDICTION.marketRegime} tone="negative" />
            <Stat label="Portfolio Health" value={`${ML_PREDICTION.portfolioHealth} / 100`} />
          </div>

          <Panel title="Regime Timeline">
            <RegimeTimeline regimes={ML_PREDICTION.regimeTimeline} />
          </Panel>

          <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
            <Panel title="Prediction Confidence">
              <div className="flex items-center gap-4">
                <div className="mono text-3xl font-semibold text-[var(--color-text-primary)]">
                  {ML_PREDICTION.confidencePct}%
                </div>
                <div className="h-2 flex-1 overflow-hidden rounded bg-[var(--color-bg-3)]">
                  <div
                    className="h-full rounded bg-[var(--color-accent)]"
                    style={{ width: `${ML_PREDICTION.confidencePct}%` }}
                  />
                </div>
              </div>
            </Panel>
            <Panel title="Feature Importance">
              <ContributionBars
                data={ML_PREDICTION.featureImportance.map((f) => ({ label: f.feature, value: f.impact }))}
                suffix=""
              />
            </Panel>
          </div>

          <div className="flex flex-wrap justify-end gap-3">
            {nextPending && (
              <Button variant="secondary" icon={ArrowRight} onClick={() => navigate(RISK_MODULES[nextPending].route)}>
                Next: {RISK_MODULES[nextPending].title}
              </Button>
            )}
            <Button icon={ArrowLeft} onClick={() => navigate('/risk/overview')}>
              Back to Risk Analysis
            </Button>
          </div>
        </>
      )}
    </div>
  )
}

function Stat({ label, value, tone }: { label: string; value: string; tone?: 'negative' }) {
  return (
    <div className="qs-panel rounded p-4">
      <div className="text-xs font-medium uppercase tracking-wide text-[var(--color-text-muted)]">{label}</div>
      <div
        className={`mono mt-1.5 text-xl font-semibold ${tone === 'negative' ? 'text-[var(--color-risk-elevated)]' : 'text-[var(--color-text-primary)]'}`}
      >
        {value}
      </div>
    </div>
  )
}
