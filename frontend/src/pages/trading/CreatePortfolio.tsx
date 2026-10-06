import { ArrowRight } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import Button from '../../components/forms/Button'
import Panel from '../../components/layout/Panel'
import PageHeader from '../../components/layout/PageHeader'
import { useDemoStore } from '../../demo/demoState'
import { PORTFOLIO, STRATEGY } from '../../services/mock/data'

export default function CreatePortfolio() {
  const navigate = useNavigate()
  const advanceTo = useDemoStore((s) => s.advanceTo)

  return (
    <div className="qs-fade-in flex flex-col gap-6">
      <PageHeader
        eyebrow="Step 5 of 8 — Trading"
        title="Create Portfolio"
        breadcrumbs={[{ label: 'Portfolios', to: '/trading/portfolios' }, { label: 'New' }]}
      />

      <Panel title="Strategy" subtitle={STRATEGY.name}>
        <ul className="list-disc space-y-1 pl-5 text-sm text-[var(--color-text-secondary)]">
          {STRATEGY.description.map((d) => (
            <li key={d}>{d}</li>
          ))}
        </ul>
      </Panel>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        <Panel title="Portfolio">
          <dl className="grid grid-cols-2 gap-4 text-sm">
            <div>
              <dt className="text-xs text-[var(--color-text-muted)]">Starting Capital</dt>
              <dd className="mono mt-0.5 text-base font-semibold text-[var(--color-text-primary)]">
                ${PORTFOLIO.startingCapital.toLocaleString()}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-[var(--color-text-muted)]">Base Currency</dt>
              <dd className="mono mt-0.5 text-base font-semibold text-[var(--color-text-primary)]">{PORTFOLIO.baseCurrency}</dd>
            </div>
          </dl>

          <div className="mt-5">
            <div className="mb-2 text-xs font-medium uppercase tracking-wide text-[var(--color-text-muted)]">Positions</div>
            <div className="flex flex-col gap-2">
              {PORTFOLIO.positions.map((p) => (
                <div key={p.symbol} className="flex items-center gap-3">
                  <span className="mono w-14 text-sm font-medium text-[var(--color-text-primary)]">{p.symbol}</span>
                  <div className="h-2 flex-1 overflow-hidden rounded bg-[var(--color-bg-3)]">
                    <div className="h-full rounded bg-[var(--color-accent)]" style={{ width: `${p.weight}%` }} />
                  </div>
                  <span className="mono w-10 text-right text-sm text-[var(--color-text-secondary)]">{p.weight}%</span>
                </div>
              ))}
            </div>
          </div>
        </Panel>

        <Panel title="Execution Assumptions">
          <dl className="grid grid-cols-2 gap-4 text-sm">
            <div>
              <dt className="text-xs text-[var(--color-text-muted)]">Transaction Cost</dt>
              <dd className="mono mt-0.5 text-base font-semibold text-[var(--color-text-primary)]">{PORTFOLIO.transactionCostPct}%</dd>
            </div>
            <div>
              <dt className="text-xs text-[var(--color-text-muted)]">Slippage</dt>
              <dd className="mono mt-0.5 text-base font-semibold text-[var(--color-text-primary)]">{PORTFOLIO.slippagePct}%</dd>
            </div>
          </dl>
        </Panel>
      </div>

      <div className="flex justify-end">
        <Button
          icon={ArrowRight}
          onClick={() => {
            advanceTo('PORTFOLIO_CREATED')
            navigate('/trading/replay/1042')
          }}
        >
          Run Strategy
        </Button>
      </div>
    </div>
  )
}
