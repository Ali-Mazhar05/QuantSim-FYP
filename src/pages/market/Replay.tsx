import { Pause, Play } from 'lucide-react'
import { useState } from 'react'
import CandlestickChart from '../../components/charts/CandlestickChart'
import Button from '../../components/forms/Button'
import Panel from '../../components/layout/Panel'
import PageHeader from '../../components/layout/PageHeader'
import ProgressBar from '../../components/status/ProgressBar'

export default function Replay() {
  const [playing, setPlaying] = useState(false)
  const [pct] = useState(42)

  return (
    <div className="qs-fade-in flex flex-col gap-6">
      <PageHeader title="Replay" description="Step through a historical market environment session by session." />
      <Panel title="US Equities — Historical Replay" subtitle="2023-01-01 → 2025-12-31 · Daily">
        <CandlestickChart seed={5} start={180} vol={0.017} count={120} />
        <div className="mt-5 flex items-center gap-4">
          <Button variant="secondary" size="sm" icon={playing ? Pause : Play} onClick={() => setPlaying((v) => !v)}>
            {playing ? 'Pause' : 'Play'}
          </Button>
          <div className="flex-1">
            <ProgressBar pct={pct} />
          </div>
          <span className="mono text-xs text-[var(--color-text-muted)]">Session 315 / 750</span>
        </div>
      </Panel>
    </div>
  )
}
