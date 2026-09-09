import { ArrowLeft, ArrowRight } from 'lucide-react'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import CorrelationHeatmap from '../../components/charts/CorrelationHeatmap'
import NetworkGraph from '../../components/charts/NetworkGraph'
import PersistenceDiagram from '../../components/charts/PersistenceDiagram'
import PersistenceLandscape from '../../components/charts/PersistenceLandscape'
import ShiftTimeline from '../../components/charts/ShiftTimeline'
import Button from '../../components/forms/Button'
import ExplainThis from '../../components/forms/ExplainThis'
import Panel from '../../components/layout/Panel'
import PageHeader from '../../components/layout/PageHeader'
import RiskBadge from '../../components/status/RiskBadge'
import { useDemoStore } from '../../demo/demoState'
import { useRiskAnalysis } from '../../demo/useRiskAnalysis'
import { TDA_ANALYSIS } from '../../services/mock/data'
import { RISK_MODULES } from '../../services/mock/riskModules'
import TdaPipelineNav from './TdaPipelineNav'

const STAGES = [
  { key: 'returns', label: 'Returns' },
  { key: 'correlation', label: 'Rolling Correlation' },
  { key: 'distance', label: 'Distance Matrix' },
  { key: 'complex', label: 'Vietoris–Rips Complex' },
  { key: 'homology', label: 'Persistent Homology' },
  { key: 'landscape', label: 'Persistence Landscape' },
  { key: 'signal', label: 'Topology Risk Signal' },
]

export default function TdaAnalysis() {
  const navigate = useNavigate()
  const startRiskModule = useDemoStore((s) => s.startRiskModule)
  const completeRiskModule = useDemoStore((s) => s.completeRiskModule)
  const { status, nextPending } = useRiskAnalysis()

  const complete = status.tda === 'complete'
  const [active, setActive] = useState(0)
  const [unlocked, setUnlocked] = useState(complete ? STAGES.length - 1 : 0)

  const next = () => {
    const n = Math.min(STAGES.length - 1, active + 1)
    setActive(n)
    setUnlocked((u) => Math.max(u, n))
    if (n === STAGES.length - 1) completeRiskModule('tda')
    else startRiskModule('tda')
  }

  return (
    <div className="qs-fade-in flex flex-col gap-6">
      <PageHeader
        title="Topological Market Structure Analysis"
        description="Detecting structural changes in asset relationships"
        breadcrumbs={[{ label: 'Risk', to: '/risk/overview' }, { label: 'TDA Analysis' }]}
        action={unlocked === STAGES.length - 1 && <RiskBadge level={TDA_ANALYSIS.level} />}
      />

      <TdaPipelineNav stages={STAGES} activeIndex={active} unlockedIndex={unlocked} onSelect={setActive} />

      {active === 0 && (
        <Panel title="Returns" subtitle="Daily log-returns for the portfolio universe">
          <p className="mb-4 text-sm text-[var(--color-text-secondary)]">
            QuantSim begins by computing daily log-returns for each instrument in the portfolio. These return
            series are the raw input to the topological pipeline — everything downstream is derived from how
            these returns move together over time.
          </p>
          <div className="flex flex-wrap gap-2">
            {TDA_ANALYSIS.assets.map((a) => (
              <span key={a} className="mono rounded border border-[var(--color-border-strong)] px-2.5 py-1 text-xs text-[var(--color-text-secondary)]">
                {a}
              </span>
            ))}
          </div>
          <div className="mt-5">
            <Button icon={ArrowRight} onClick={next}>
              Next: Rolling Correlation
            </Button>
          </div>
        </Panel>
      )}

      {active === 1 && (
        <Panel
          title="Rolling Correlation"
          subtitle="Window: 60 days · Step: 5 days"
          action={
            <ExplainThis>
              Rolling correlation measures how closely each pair of assets moves together over a moving window
              of recent trading days. As the window slides forward, the correlation matrix updates — capturing
              how relationships between assets evolve.
            </ExplainThis>
          }
        >
          <CorrelationHeatmap assets={TDA_ANALYSIS.assets} matrix={TDA_ANALYSIS.correlationMatrix} />
          <div className="mt-5">
            <Button icon={ArrowRight} onClick={next}>
              Next: Distance Matrix
            </Button>
          </div>
        </Panel>
      )}

      {active === 2 && (
        <Panel
          title="Distance Matrix"
          subtitle="Correlation converted to topological distance"
          action={
            <ExplainThis>
              The distance matrix converts correlation into a measure of how far apart two assets are in terms
              of their behaviour. Highly correlated assets sit close together; assets that move independently
              sit far apart.
            </ExplainThis>
          }
        >
          <CorrelationHeatmap
            assets={TDA_ANALYSIS.assets}
            matrix={TDA_ANALYSIS.distanceMatrix}
            // Same single-hue sequential ramp as the correlation heatmap, just
            // inverted: distance 0 (assets sitting on top of each other) is the
            // hot end, and far apart fades to near-white.
            colorFor={(v) => {
              const t = 1 - Math.max(0, Math.min(1, v / 1.4))
              const r = Math.round(242 + t * (161 - 242))
              const g = Math.round(245 + t * (15 - 245))
              const b = Math.round(248 + t * (61 - 248))
              return `rgb(${r},${g},${b})`
            }}
          />
          <div className="mt-5">
            <Button icon={ArrowRight} onClick={next}>
              Build Complex
            </Button>
          </div>
        </Panel>
      )}

      {active === 3 && (
        <Panel
          title="Vietoris–Rips Complex"
          subtitle="Assets connected when their distance falls below a threshold"
          action={
            <ExplainThis>
              QuantSim connects assets whose topological distance is below a threshold, forming a network. As
              the threshold grows, more connections appear — dense, tightly-connected networks indicate a
              market that is moving as one, reducing diversification.
            </ExplainThis>
          }
        >
          <div className="flex justify-center">
            <NetworkGraph assets={TDA_ANALYSIS.assets} distanceMatrix={TDA_ANALYSIS.distanceMatrix} threshold={0.75} />
          </div>
          <div className="mt-5">
            <Button icon={ArrowRight} onClick={next}>
              Compute Persistent Homology
            </Button>
          </div>
        </Panel>
      )}

      {active === 4 && (
        <Panel
          title="Persistence Diagram"
          subtitle="Birth and death of topological features across distance thresholds"
          action={
            <ExplainThis>
              As the connection threshold grows, topological features — connected clusters (H0) and loops (H1)
              — appear ("birth") and later merge or close ("death"). Points far from the diagonal represent
              persistent, structurally significant features rather than noise.
            </ExplainThis>
          }
        >
          <div className="flex justify-center">
            <PersistenceDiagram points={TDA_ANALYSIS.persistencePoints} />
          </div>
          <div className="mt-5">
            <Button icon={ArrowRight} onClick={next}>
              Generate Persistence Landscape
            </Button>
          </div>
        </Panel>
      )}

      {active === 5 && (
        <Panel
          title="Persistence Landscape"
          subtitle="Persistence diagram summarized as a functional curve"
          action={
            <ExplainThis>
              The persistence landscape transforms the diagram's scattered points into smooth, comparable
              curves. This makes it possible to track how the market's topological structure changes over time
              and to feed that signal into a risk score.
            </ExplainThis>
          }
        >
          <PersistenceLandscape curves={TDA_ANALYSIS.landscapeCurves} />
          <div className="mt-5">
            <Button icon={ArrowRight} onClick={next}>
              View Topology Signal
            </Button>
          </div>
        </Panel>
      )}

      {active === 6 && (
        <>
          <Panel title="Topology Signal">
            <div className="flex flex-col items-center gap-2 py-4">
              <span className="text-xs font-medium uppercase tracking-wide text-[var(--color-text-muted)]">Current structural risk</span>
              <span className="mono text-5xl font-bold text-[var(--color-text-primary)]">{TDA_ANALYSIS.score}<span className="text-xl text-[var(--color-text-muted)]"> / 100</span></span>
              <RiskBadge level={TDA_ANALYSIS.level} size="lg" />
              <span className="mt-1 text-sm text-[var(--color-text-secondary)]">Structural deformation detected</span>
            </div>
            <ShiftTimeline shiftLabel="Topology shift" shiftPositionPct={68} />
            <p className="mt-2 text-xs text-[var(--color-text-muted)]">
              This is a visual demonstration of the QuantSim topology pipeline, not a live mathematical
              computation. The persistence landscape values above are controlled demo data.
            </p>
          </Panel>
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
