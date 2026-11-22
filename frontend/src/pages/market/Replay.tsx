import { Pause, Play } from 'lucide-react'
import { useEffect, useState } from 'react'
import CandlestickChart from '../../components/charts/CandlestickChart'
import Button from '../../components/forms/Button'
import Panel from '../../components/layout/Panel'
import PageHeader from '../../components/layout/PageHeader'
import EmptyState from '../../components/status/EmptyState'
import ProgressBar from '../../components/status/ProgressBar'
import { useEnvironments } from '../../hooks/useEnvironments'
import { type Candle, getCandles } from '../../services/api/market'
import { errorMessage } from '../auth/authShared'

// Playback (FR-MKT-007) arrives in Iteration 2; until then the controls keep the
// prototype's position over the active environment's real sessions
const PROTOTYPE_POSITION_PCT = 42

type Series = { key: string; candles: Candle[] } | { key: string; error: string }

export default function Replay() {
  const [playing, setPlaying] = useState(false)
  const [pct] = useState(PROTOTYPE_POSITION_PCT)
  const { environments, error, active } = useEnvironments()
  const [series, setSeries] = useState<Series | null>(null)

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
  const total = current && 'candles' in current ? current.candles.length : 0
  const position = Math.round((pct / 100) * total)

  let body
  if (error) {
    body = <p role="alert" className="text-sm text-[var(--color-risk-severe)]">{error.message}</p>
  } else if (environments === null || (active && !current)) {
    body = <p className="text-sm text-[var(--color-text-muted)]">Loading…</p>
  } else if (!active) {
    body = <EmptyState title="No environment yet" description="Create a market environment to replay it here." />
  } else if (current && 'error' in current) {
    body = <p role="alert" className="text-sm text-[var(--color-risk-severe)]">{current.error}</p>
  } else if (total === 0) {
    body = <EmptyState title="No observations in this window" description="The environment's instruments have no ingested sessions in its window yet." />
  } else if (current && 'candles' in current) {
    body = <CandlestickChart candles={current.candles} />
  }

  return (
    <div className="qs-fade-in flex flex-col gap-6">
      <PageHeader title="Replay" description="Step through a historical market environment session by session." />
      <Panel
        title={active ? `${active.name} — ${active.type}` : 'Replay'}
        subtitle={active ? `${active.start} → ${active.end} · ${active.frequency}` : undefined}
      >
        {body}
        <div className="mt-5 flex items-center gap-4">
          <Button variant="secondary" size="sm" icon={playing ? Pause : Play} onClick={() => setPlaying((v) => !v)}>
            {playing ? 'Pause' : 'Play'}
          </Button>
          <div className="flex-1">
            <ProgressBar pct={pct} />
          </div>
          <span className="mono text-xs text-[var(--color-text-muted)]">
            Session {position} / {total}
          </span>
        </div>
      </Panel>
    </div>
  )
}
