import { ArrowRight, RotateCcw } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import MonteCarloFanChart from '../../components/charts/MonteCarloFanChart'
import Button from '../../components/forms/Button'
import Panel from '../../components/layout/Panel'
import PageHeader from '../../components/layout/PageHeader'
import ProgressBar from '../../components/status/ProgressBar'
import StatusPill from '../../components/status/StatusPill'
import { useDemoStore } from '../../demo/demoState'

const LOG_TEMPLATE = [
  'Calibration validated',
  'Simulation job queued',
  'Worker 01 started',
  'Worker 02 started',
  'Worker 03 started',
  'Worker 04 started',
  '2,500 paths completed',
  '5,000 paths completed',
  '7,500 paths completed',
  '10,000 paths completed',
]

function nowTime(offsetSec: number) {
  const d = new Date(2026, 7, 25, 12, 31, 4 + offsetSec)
  return d.toTimeString().slice(0, 8)
}

type Phase = 'running' | 'complete' | 'failed'

export default function RunSimulation() {
  const { id = '1042' } = useParams()
  const navigate = useNavigate()
  const advanceTo = useDemoStore((s) => s.advanceTo)
  const [pct, setPct] = useState(0)
  const [phase, setPhase] = useState<Phase>('running')
  const [logCount, setLogCount] = useState(0)
  const [elapsed, setElapsed] = useState(0)

  useEffect(() => {
    if (phase !== 'running') return
    const interval = setInterval(() => {
      setElapsed((e) => e + 1)
      setPct((p) => {
        const next = Math.min(100, p + (5 + Math.random() * 6))
        return next
      })
      setLogCount((c) => Math.min(LOG_TEMPLATE.length, c + 1))
    }, 550)
    return () => clearInterval(interval)
  }, [phase])

  useEffect(() => {
    if (pct >= 100 && phase === 'running') {
      const t = setTimeout(() => {
        setPhase('complete')
        advanceTo('SIMULATION_COMPLETE')
      }, 400)
      return () => clearTimeout(t)
    }
  }, [pct, phase, advanceTo])

  const pathsGenerated = Math.round((pct / 100) * 10000)
  const remaining = Math.max(0, Math.round((100 - pct) / 6))

  return (
    <div className="qs-fade-in flex flex-col gap-6">
      <PageHeader
        eyebrow="Step 3 of 8 — Simulation"
        title={`Simulation #${id}`}
        description="Generating Monte Carlo Ensemble"
        breadcrumbs={[{ label: 'Simulations', to: '/simulation/runs' }, { label: `#${id}` }]}
        action={
          <StatusPill tone={phase === 'complete' ? 'success' : phase === 'failed' ? 'danger' : 'info'} dot>
            {phase === 'complete' ? 'Complete' : phase === 'failed' ? 'Failed' : 'Running'}
          </StatusPill>
        }
      />

      <Panel>
        <div className="mb-4 flex items-center justify-between">
          <span className="text-sm font-medium text-[var(--color-text-primary)]">
            {phase === 'complete' ? 'Simulation Complete' : phase === 'failed' ? 'Simulation Failed' : 'Generating Monte Carlo Ensemble'}
          </span>
          <span className="mono text-sm text-[var(--color-text-secondary)]">{Math.round(pct)}%</span>
        </div>
        <ProgressBar pct={pct} />

        {phase === 'failed' ? (
          <div className="mt-6 rounded border border-[var(--color-risk-severe)]/40 bg-[var(--color-risk-severe)]/10 p-4">
            <div className="text-sm font-semibold text-[var(--color-risk-high)]">Worker unavailable.</div>
            <div className="mt-3">
              <Button
                variant="secondary"
                icon={RotateCcw}
                onClick={() => {
                  setPhase('running')
                  setPct(0)
                  setLogCount(0)
                }}
              >
                Retry
              </Button>
            </div>
          </div>
        ) : (
          <div className="mt-5 grid grid-cols-2 gap-4 sm:grid-cols-4">
            <Stat label="Paths generated" value={`${pathsGenerated.toLocaleString()} / 10,000`} />
            <Stat label="Workers" value="4 active" />
            <Stat label="Elapsed" value={`00:${String(elapsed).padStart(2, '0')}`} />
            <Stat label="Est. remaining" value={phase === 'complete' ? '00:00' : `00:${String(remaining).padStart(2, '0')}`} />
          </div>
        )}
      </Panel>

      <Panel title="Monte Carlo Ensemble" subtitle="AAPL · GBM · 252 steps">
        <MonteCarloFanChart revealPct={phase === 'complete' ? 100 : pct} height={260} />
      </Panel>

      <Panel title="Event Log">
        <div className="mono flex flex-col gap-1.5 text-xs">
          {LOG_TEMPLATE.slice(0, logCount).map((msg, i) => (
            <div key={i} className="qs-fade-in flex gap-3 text-[var(--color-text-secondary)]">
              <span className="text-[var(--color-text-muted)]">{nowTime(i)}</span>
              <span>{msg}</span>
            </div>
          ))}
          {logCount === 0 && <div className="text-[var(--color-text-muted)]">Waiting for job to start…</div>}
        </div>
      </Panel>

      {phase === 'complete' && (
        <div className="flex justify-end">
          <Button icon={ArrowRight} onClick={() => navigate(`/simulation/results/${id}`)}>
            View Results
          </Button>
        </div>
      )}
    </div>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs text-[var(--color-text-muted)]">{label}</div>
      <div className="mono mt-0.5 text-sm font-semibold text-[var(--color-text-primary)]">{value}</div>
    </div>
  )
}
