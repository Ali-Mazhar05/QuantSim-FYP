import { useState } from 'react'
import CandlestickChart from '../../components/charts/CandlestickChart'
import Panel from '../../components/layout/Panel'
import PageHeader from '../../components/layout/PageHeader'
import { INSTRUMENTS } from '../../services/mock/data'

export default function MarketData() {
  const [symbol, setSymbol] = useState('AAPL')
  const inst = INSTRUMENTS.find((i) => i.symbol === symbol)!
  const seed = INSTRUMENTS.findIndex((i) => i.symbol === symbol) + 1

  return (
    <div className="qs-fade-in flex flex-col gap-6">
      <PageHeader title="Market Data" description="Daily OHLC series for instruments within the active market environment." />
      <div className="flex flex-wrap gap-2">
        {INSTRUMENTS.map((i) => (
          <button
            key={i.symbol}
            onClick={() => setSymbol(i.symbol)}
            className={`mono rounded border px-3 py-1.5 text-xs font-semibold ${
              symbol === i.symbol
                ? 'border-[var(--color-accent-strong)] bg-[var(--color-accent)]/12 text-[var(--color-accent-strong)]'
                : 'border-[var(--color-border-strong)] text-[var(--color-text-secondary)] hover:border-[var(--color-border-strong)]/80'
            }`}
          >
            {i.symbol}
          </button>
        ))}
      </div>
      <Panel title={`${inst.name} (${inst.symbol})`} subtitle="Daily · last 90 sessions">
        <CandlestickChart seed={seed} start={inst.price * 0.9} vol={0.02} count={90} />
      </Panel>
    </div>
  )
}
