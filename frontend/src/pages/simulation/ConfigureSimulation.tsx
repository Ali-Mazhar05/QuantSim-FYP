import { useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { ArrowRight } from 'lucide-react'
import { useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Button from '../../components/forms/Button'
import Panel from '../../components/layout/Panel'
import PageHeader from '../../components/layout/PageHeader'
import ErrorNote from '../../components/status/ErrorNote'
import ExtendedScopeBadge from '../../components/status/ExtendedScopeBadge'
import StatusPill from '../../components/status/StatusPill'
import { useCan } from '../../demo/useCan'
import { classifyError } from '../../hooks/apiError'
import { simulationKeys } from '../../hooks/keys/simulation'
import { useEnvironments } from '../../hooks/useEnvironments'
import { useCalibrations, useCreateRun } from '../../hooks/useSimulation'
import { CalibrationRefusedError, type ModelName, ensureCalibrations } from '../../services/api/simulation'

// The demo size of a run (DL-041): 1,000 paths of 252 sessions, stored in full.
export const PATHS = 1000
export const STEPS = 252

// Regime switching has no generator or fit in this iteration: shown as Extended, not selectable.
const MODELS: { id: ModelName | null; name: string; description: string; extended?: boolean }[] = [
  { id: 'gbm', name: 'GBM', description: 'Geometric Brownian Motion' },
  { id: 'merton', name: 'Jump Diffusion', description: 'Diffusion with discrete jump events' },
  { id: 'ou', name: 'Ornstein-Uhlenbeck', description: 'Mean-reverting stochastic process' },
  { id: null, name: 'Regime Switching', description: 'Markov-modulated volatility regimes', extended: true },
]

type Phase = 'idle' | 'fitting' | 'starting'

export default function ConfigureSimulation() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const canLaunch = useCan('launch_simulations')
  const { active, environments, error: environmentError } = useEnvironments()
  const { calibrations } = useCalibrations()
  const createRun = useCreateRun()
  const [model, setModel] = useState<ModelName>('gbm')
  const [phase, setPhase] = useState<Phase>('idle')
  const [problem, setProblem] = useState<string | null>(null)
  // one key per page visit: a double click starts one run, not two
  const runKey = useRef(crypto.randomUUID())

  const chosen = MODELS.find((m) => m.id === model)
  const symbols = active?.instruments ?? []
  const fitted = active
    ? calibrations?.find(
        (c) =>
          c.calibration?.model === model &&
          c.calibration.instrument_id === active.instrumentIds[0] &&
          c.calibration.window_start === active.start &&
          c.calibration.window_end === active.end,
      )
    : undefined
  const busy = phase !== 'idle'

  async function start() {
    if (!active) return
    setProblem(null)
    setPhase('fitting')
    try {
      const instruments = active.instrumentIds.map((id, i) => ({ id, symbol: active.instruments[i] ?? id }))
      const existing = calibrations ?? []
      const ids = await ensureCalibrations({
        model,
        instruments,
        start: active.start,
        end: active.end,
        existing,
      })
      await queryClient.invalidateQueries({ queryKey: simulationKeys.calibrations() })
      setPhase('starting')
      const run = await createRun.mutateAsync({
        body: {
          model,
          instruments: instruments.map((inst, i) => ({ instrument_id: inst.id, calibration_id: ids[i] })),
          n_paths: PATHS,
          n_steps: STEPS,
        },
        key: runKey.current,
      })
      navigate(`/simulation/run/${run.id}`)
    } catch (error) {
      setProblem(
        error instanceof CalibrationRefusedError
          ? `The ${chosen?.name} model was refused for ${error.symbol}: ${error.reason}`
          : classifyError(error).message,
      )
      setPhase('idle')
    }
  }

  return (
    <div className="qs-fade-in flex flex-col gap-6" data-testid="page-configure">
      <PageHeader
        eyebrow="Step 2 of 8 — Simulation"
        title="Simulation Configuration"
        description="Select a stochastic model and calibration source, then generate the Monte Carlo ensemble."
        breadcrumbs={[{ label: 'Simulations', to: '/simulation/runs' }, { label: 'Configure' }]}
      />

      {environmentError && <ErrorNote error={environmentError} />}
      {environments !== null && !active && (
        <p role="status" className="text-sm text-[var(--color-text-secondary)]">
          There is no market environment to simulate yet. Create one first.
        </p>
      )}

      <Panel title="Model">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {MODELS.map((m) => {
            const selectable = m.id !== null
            const selected = m.id === model
            return (
              <button
                key={m.name}
                type="button"
                disabled={!selectable || busy}
                aria-pressed={selected}
                data-testid={`model-${m.id ?? 'extended'}`}
                onClick={() => m.id && setModel(m.id)}
                className={clsx(
                  'rounded border p-4 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-60',
                  selected
                    ? 'border-[var(--color-accent-strong)] bg-[var(--color-accent)]/8'
                    : 'border-[var(--color-border-strong)] hover:border-[var(--color-border-strong)]/80',
                )}
              >
                <div className="flex items-center gap-1.5">
                  <span className={clsx('text-sm font-semibold', selected ? 'text-[var(--color-accent-strong)]' : 'text-[var(--color-text-primary)]')}>
                    {m.name}
                  </span>
                  {m.extended && <ExtendedScopeBadge compact />}
                </div>
                <div className="mt-1 text-xs text-[var(--color-text-muted)]">
                  {m.description}
                  {m.extended ? ' — not available yet' : ''}
                </div>
              </button>
            )
          })}
        </div>
      </Panel>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        <Panel title="Run Parameters">
          <dl className="grid grid-cols-2 gap-4 text-sm">
            <Item label="Environment" value={active?.name ?? '—'} />
            <Item label="Instruments" value={symbols.join(', ') || '—'} mono />
            <Item label="Paths" value={PATHS.toLocaleString()} mono />
            <Item label="Time Steps" value={String(STEPS)} mono />
            <Item label="Confidence" value="95%" mono />
          </dl>
        </Panel>

        <Panel
          title="Calibration Summary"
          subtitle={active ? `${chosen?.name} on ${active.start} to ${active.end}` : undefined}
          action={
            <StatusPill tone={fitted ? 'success' : 'neutral'}>{fitted ? 'Fitted' : 'Fitted when the run starts'}</StatusPill>
          }
        >
          {fitted?.calibration ? (
            <dl className="grid grid-cols-2 gap-4 text-sm">
              {Object.entries(fitted.calibration.params).map(([name, value]) => (
                <Item key={name} label={name} value={Number(value).toPrecision(4)} mono />
              ))}
              <Item label="Returns" value={String(fitted.calibration.n_obs)} mono />
              <Item label="Converged" value={fitted.calibration.converged ? 'Yes' : 'No'} />
            </dl>
          ) : (
            <p className="text-sm text-[var(--color-text-secondary)]">
              The model is fitted to the environment&apos;s prices for each instrument when you run the simulation.
            </p>
          )}
        </Panel>
      </div>

      {problem && (
        <p role="alert" data-testid="configure-problem" className="text-sm text-[var(--color-risk-severe)]">
          {problem}
        </p>
      )}
      {phase !== 'idle' && (
        <p role="status" data-testid="configure-phase" className="text-sm text-[var(--color-text-secondary)]">
          {phase === 'fitting' ? `Fitting the ${chosen?.name} model to ${symbols.length} instrument${symbols.length === 1 ? '' : 's'}…` : 'Starting the simulation…'}
        </p>
      )}
      {!canLaunch && (
        <p className="text-sm text-[var(--color-text-muted)]">Your role can read simulations but not start one.</p>
      )}

      <div className="flex justify-end">
        <Button icon={ArrowRight} disabled={!canLaunch || !active || busy} onClick={() => void start()}>
          Run Simulation
        </Button>
      </div>
    </div>
  )
}

function Item({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div>
      <dt className="text-xs text-[var(--color-text-muted)]">{label}</dt>
      <dd className={clsx('mt-0.5 text-[var(--color-text-primary)]', mono && 'mono')}>{value}</dd>
    </div>
  )
}
