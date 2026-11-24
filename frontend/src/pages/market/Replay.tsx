import clsx from 'clsx'
import { Pause, Play } from 'lucide-react'
import { useEffect, useState } from 'react'
import CandlestickChart from '../../components/charts/CandlestickChart'
import Button from '../../components/forms/Button'
import Panel from '../../components/layout/Panel'
import PageHeader from '../../components/layout/PageHeader'
import EmptyState from '../../components/status/EmptyState'
import ErrorNote from '../../components/status/ErrorNote'
import ProgressBar from '../../components/status/ProgressBar'
import { useCan } from '../../demo/useCan'
import { classifyError } from '../../hooks/apiError'
import { useEnvironments } from '../../hooks/useEnvironments'
import { useReplayControls, useReplaySession } from '../../hooks/useReplay'
import { type Candle, getCandles } from '../../services/api/market'
import { SPEEDS } from '../../services/api/replay'
import { errorMessage } from '../auth/authShared'

type Series = { key: string; candles: Candle[] } | { key: string; error: string }

export default function Replay() {
  const canControl = useCan('create_market_environments')
  const { environments, error, active } = useEnvironments()
  const { session, loaded, error: sessionError } = useReplaySession(active?.id)
  const controls = useReplayControls(active?.id, active?.status === 'Active')
  const [series, setSeries] = useState<Series | null>(null)
  // while the slider is held the page shows where it is, and only on release is the server told
  const [seeking, setSeeking] = useState<number | null>(null)

  const instrumentId = active?.instrumentIds[0]
  const key = active && instrumentId ? `${active.id}:${instrumentId}` : null
  const start = active?.start
  const end = active?.end
  useEffect(() => {
    if (!key || !instrumentId || !start || !end) return
    let cancelled = false
    getCandles(instrumentId, start, end)
      .then((candles) => !cancelled && setSeries({ key, candles }))
      .catch((failure: unknown) => !cancelled && setSeries({ key, error: errorMessage(failure) }))
    return () => {
      cancelled = true
    }
  }, [key, instrumentId, start, end])

  const current = series && series.key === key ? series : null
  const candles = current && 'candles' in current ? current.candles : []
  const count = session?.session_count ?? candles.length
  const position = seeking ?? session?.position ?? 0
  const playing = session?.state === 'playing' && !session.finished
  const pct = count > 1 ? (position / (count - 1)) * 100 : session?.finished ? 100 : 0
  // the chart shows what has been replayed so far: the sessions up to the server's date
  const shownUntil = session?.session_date ?? null
  const shown = session && shownUntil ? candles.filter((c) => c.date <= shownUntil) : candles
  const problem = controls.error ? classifyError(controls.error).message : null
  const busy = controls.isPending

  const send = (action: Parameters<typeof controls.mutate>[0]['action']) => controls.mutate({ action, session })

  let body
  if (error) {
    body = <ErrorNote error={error} />
  } else if (environments === null || (active && !current) || (active && !loaded && !sessionError)) {
    body = <p className="text-sm text-[var(--color-text-muted)]">Loading…</p>
  } else if (!active) {
    body = <EmptyState title="No environment yet" description="Create a market environment to replay it here." />
  } else if (current && 'error' in current) {
    body = (
      <p role="alert" className="text-sm text-[var(--color-risk-severe)]">
        {current.error}
      </p>
    )
  } else if (candles.length === 0) {
    body = <EmptyState title="No observations in this window" description="The environment's instruments have no ingested sessions in its window yet." />
  } else {
    body = <CandlestickChart candles={shown} />
  }

  return (
    <div className="qs-fade-in flex flex-col gap-6" data-testid="page-replay">
      <PageHeader title="Replay" description="Step through a historical market environment session by session." />
      <Panel
        title={active ? `${active.name} — ${active.type}` : 'Replay'}
        subtitle={active ? `${active.start} → ${active.end} · ${active.frequency}` : undefined}
      >
        {body}
        {sessionError && <ErrorNote error={sessionError} />}
        {active && (
          <>
            <div className="mt-5 flex flex-wrap items-center gap-4">
              <Button
                variant="secondary"
                size="sm"
                icon={playing ? Pause : Play}
                disabled={!canControl || busy}
                data-testid="replay-toggle"
                onClick={() => send({ kind: playing ? 'pause' : 'play' })}
              >
                {playing ? 'Pause' : 'Play'}
              </Button>
              <div role="group" aria-label="Replay speed" className="flex gap-1">
                {SPEEDS.map((speed) => (
                  <button
                    key={speed}
                    type="button"
                    aria-pressed={(session?.speed ?? 1) === speed}
                    disabled={!canControl || busy || !session}
                    data-testid={`replay-speed-${speed}`}
                    onClick={() => send({ kind: 'speed', speed })}
                    className={clsx(
                      'mono rounded border px-2 py-1 text-xs disabled:cursor-not-allowed disabled:opacity-50',
                      (session?.speed ?? 1) === speed
                        ? 'border-[var(--color-accent-strong)] text-[var(--color-accent-strong)]'
                        : 'border-[var(--color-border-strong)] text-[var(--color-text-secondary)]',
                    )}
                  >
                    {speed}x
                  </button>
                ))}
              </div>
              <div className="min-w-[160px] flex-1">
                <input
                  type="range"
                  aria-label="Seek"
                  data-testid="replay-seek"
                  min={0}
                  max={Math.max(0, count - 1)}
                  value={position}
                  disabled={!canControl || busy || !session || count < 2}
                  aria-valuetext={`Session ${position + 1} of ${count}`}
                  onChange={(e) => setSeeking(Number(e.target.value))}
                  onPointerUp={() => {
                    if (seeking !== null) send({ kind: 'seek', index: seeking })
                    setSeeking(null)
                  }}
                  onKeyUp={() => {
                    if (seeking !== null) send({ kind: 'seek', index: seeking })
                    setSeeking(null)
                  }}
                  className="w-full"
                />
                <ProgressBar pct={pct} />
              </div>
              <span className="mono text-xs text-[var(--color-text-muted)]" data-testid="replay-position">
                Session {count === 0 ? 0 : position + 1} / {count}
                {session?.session_date ? ` · ${session.session_date}` : ''}
                {session?.finished ? ' · finished' : ''}
              </span>
            </div>
            {!canControl && (
              <p className="mt-3 text-xs text-[var(--color-text-muted)]" data-testid="replay-readonly">
                Your role can watch a replay but not control it.
              </p>
            )}
            {session?.current_fingerprint && session.current_fingerprint !== session.source_fingerprint && (
              <p role="status" className="mt-3 text-xs text-[var(--color-risk-elevated)]">
                The stored data has changed since this environment was activated.
              </p>
            )}
            {problem && (
              <p role="alert" className="mt-3 text-sm text-[var(--color-risk-severe)]">
                {problem}
              </p>
            )}
          </>
        )}
      </Panel>
    </div>
  )
}
