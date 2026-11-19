import { ArrowRight } from 'lucide-react'
import { useNavigate, useParams } from 'react-router-dom'
import MonteCarloFanChart from '../../components/charts/MonteCarloFanChart'
import Button from '../../components/forms/Button'
import { useCan } from '../../demo/useCan'
import Panel from '../../components/layout/Panel'
import PageHeader from '../../components/layout/PageHeader'
import StatusPill from '../../components/status/StatusPill'
import { useDemoStore } from '../../demo/demoState'

export default function SimulationResults() {
  const { id = '1042' } = useParams()
  const navigate = useNavigate()
  const canCreate = useCan('create_portfolios')
  const advanceTo = useDemoStore((s) => s.advanceTo)

  return (
    <div className="qs-fade-in flex flex-col gap-6">
      <PageHeader
        eyebrow="Step 4 of 8 — Simulation"
        title={`Simulation #${id}`}
        breadcrumbs={[{ label: 'Simulations', to: '/simulation/runs' }, { label: `#${id}` }]}
        description="GBM · AAPL · 10,000 paths · 252 steps"
        action={<StatusPill tone="success" dot>Complete</StatusPill>}
      />

      <div className="grid grid-cols-1 gap-5 xl:grid-cols-[1.6fr_1fr]">
        <Panel title="Monte Carlo Fan Chart" subtitle="Simulated terminal price distribution">
          <MonteCarloFanChart height={320} />
        </Panel>

        <div className="flex flex-col gap-5">
          <Panel title="Terminal Price">
            <dl className="grid grid-cols-2 gap-4 text-sm">
              <Stat label="Mean" value="$238.41" />
              <Stat label="Median" value="$234.80" />
              <Stat label="5th %ile" value="$181.22" />
              <Stat label="95th %ile" value="$312.17" />
            </dl>
          </Panel>
          <Panel title="Risk Summary">
            <dl className="grid grid-cols-2 gap-4 text-sm">
              <Stat label="VaR 95%" value="-8.7%" tone="negative" />
              <Stat label="CVaR 95%" value="-12.9%" tone="negative" />
            </dl>
          </Panel>
        </div>
      </div>

      <div className="flex justify-end">
        <Button
          icon={ArrowRight}
          disabled={!canCreate}
          onClick={() => {
            advanceTo('SIMULATION_COMPLETE')
            navigate('/trading/portfolios/new')
          }}
        >
          Create Portfolio
        </Button>
      </div>
    </div>
  )
}

function Stat({ label, value, tone }: { label: string; value: string; tone?: 'negative' }) {
  return (
    <div>
      <dt className="text-xs text-[var(--color-text-muted)]">{label}</dt>
      <dd className={`mono mt-0.5 text-base font-semibold ${tone === 'negative' ? 'text-[var(--color-risk-severe)]' : 'text-[var(--color-text-primary)]'}`}>
        {value}
      </dd>
    </div>
  )
}
