import { Plus } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import Button from '../../components/forms/Button'
import Panel from '../../components/layout/Panel'
import PageHeader from '../../components/layout/PageHeader'
import { STRATEGY } from '../../services/mock/data'

export default function Strategies() {
  const navigate = useNavigate()
  return (
    <div className="qs-fade-in flex flex-col gap-6">
      <PageHeader
        title="Strategies"
        description="Trading strategies available for portfolio construction."
        action={
          <Button icon={Plus} onClick={() => navigate('/trading/portfolios/new')}>
            New Strategy
          </Button>
        }
      />
      <Panel title={STRATEGY.name} subtitle={`Rebalance: ${STRATEGY.rebalance} · Max position: ${STRATEGY.maxPosition}%`}>
        <ul className="list-disc space-y-1 pl-5 text-sm text-[var(--color-text-secondary)]">
          {STRATEGY.description.map((d) => (
            <li key={d}>{d}</li>
          ))}
        </ul>
      </Panel>
    </div>
  )
}
