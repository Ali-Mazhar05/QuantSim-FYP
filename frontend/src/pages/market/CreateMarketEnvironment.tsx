import clsx from 'clsx'
import { ArrowRight } from 'lucide-react'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import CandlestickChart from '../../components/charts/CandlestickChart'
import Button from '../../components/forms/Button'
import Panel from '../../components/layout/Panel'
import PageHeader from '../../components/layout/PageHeader'
import { useDemoStore } from '../../demo/demoState'
import { INSTRUMENTS } from '../../services/mock/data'
import type { MarketEnvironment } from '../../types'

export default function CreateMarketEnvironment() {
  const navigate = useNavigate()
  const advanceTo = useDemoStore((s) => s.advanceTo)
  const [type, setType] = useState<MarketEnvironment['type']>('Synthetic Market')
  const [selected, setSelected] = useState<string[]>(['AAPL', 'MSFT', 'NVDA', 'AMZN', 'GOOGL'])

  const toggle = (sym: string) => {
    setSelected((s) => (s.includes(sym) ? s.filter((x) => x !== sym) : [...s, sym]))
  }

  return (
    <div className="qs-fade-in flex flex-col gap-6">
      <PageHeader
        eyebrow="Step 1 of 8 — Market"
        title="Create Market Environment"
        description="Choose a historical replay or a synthetic market to run your simulation inside."
        breadcrumbs={[{ label: 'Market Environments', to: '/market/environments' }, { label: 'New' }]}
      />

      <Panel title="Market Type">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {(['Historical Replay', 'Synthetic Market'] as const).map((t) => (
            <button
              key={t}
              onClick={() => setType(t)}
              className={clsx(
                'rounded border p-4 text-left transition-colors',
                type === t ? 'border-[var(--color-accent-strong)] bg-[var(--color-accent)]/8' : 'border-[var(--color-border-strong)] hover:border-[var(--color-border-strong)]/80',
              )}
            >
              <div className={clsx('text-sm font-semibold', type === t ? 'text-[var(--color-accent-strong)]' : 'text-[var(--color-text-primary)]')}>{t}</div>
              <div className="mt-1 text-xs text-[var(--color-text-muted)]">
                {t === 'Historical Replay'
                  ? 'Replay recorded market data over a fixed historical window.'
                  : 'Generate a synthetic market calibrated to historical statistics.'}
              </div>
            </button>
          ))}
        </div>
      </Panel>

      <Panel title="Universe" subtitle="US Technology Basket">
        <div className="flex flex-wrap gap-2">
          {INSTRUMENTS.map((inst) => (
            <button
              key={inst.symbol}
              onClick={() => toggle(inst.symbol)}
              className={clsx(
                'mono rounded border px-3 py-1.5 text-xs font-semibold transition-colors',
                selected.includes(inst.symbol)
                  ? 'border-[var(--color-accent-strong)] bg-[var(--color-accent)]/12 text-[var(--color-accent-strong)]'
                  : 'border-[var(--color-border-strong)] text-[var(--color-text-secondary)] hover:border-[var(--color-border-strong)]/80',
              )}
            >
              {inst.symbol}
            </button>
          ))}
        </div>
      </Panel>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        <Panel title="Data Window">
          <dl className="grid grid-cols-2 gap-3 text-sm">
            <div>
              <dt className="text-xs text-[var(--color-text-muted)]">Start</dt>
              <dd className="mono mt-0.5 text-[var(--color-text-primary)]">2025-01-01</dd>
            </div>
            <div>
              <dt className="text-xs text-[var(--color-text-muted)]">End</dt>
              <dd className="mono mt-0.5 text-[var(--color-text-primary)]">2026-06-30</dd>
            </div>
            <div>
              <dt className="text-xs text-[var(--color-text-muted)]">Frequency</dt>
              <dd className="mt-0.5 text-[var(--color-text-primary)]">Daily</dd>
            </div>
            <div>
              <dt className="text-xs text-[var(--color-text-muted)]">Universe</dt>
              <dd className="mt-0.5 text-[var(--color-text-primary)]">US Technology Basket</dd>
            </div>
          </dl>
        </Panel>
        <Panel title="Preview" subtitle="AAPL — reference series">
          <CandlestickChart seed={11} start={190} vol={0.018} count={70} height={180} />
        </Panel>
      </div>

      <div className="flex justify-end">
        <Button
          icon={ArrowRight}
          onClick={() => {
            advanceTo('MARKET_SELECTED')
            navigate('/simulation/configure')
          }}
        >
          Continue to Simulation
        </Button>
      </div>
    </div>
  )
}
