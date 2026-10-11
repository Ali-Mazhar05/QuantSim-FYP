import { Plus, Settings2 } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import Button from '../../components/forms/Button'
import Panel from '../../components/layout/Panel'
import PageHeader from '../../components/layout/PageHeader'
import { STRATEGIES } from '../../services/mock/data'

export default function Strategies() {
  const navigate = useNavigate()
  return (
    <div className="qs-fade-in flex flex-col gap-6">
      <PageHeader
        title="Strategies"
        description="Trading strategies available for portfolio construction. Select one to configure its rules."
        action={
          <Button icon={Plus} onClick={() => navigate('/trading/strategies/new')}>
            New Strategy
          </Button>
        }
      />
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {STRATEGIES.map((s) => (
          <Panel
            key={s.id}
            title={s.name}
            subtitle={`Rebalance: ${s.rebalance} · Max position: ${s.maxPosition}%`}
            action={
              <Button
                variant="secondary"
                size="sm"
                icon={Settings2}
                onClick={() => navigate(`/trading/strategies/${s.id}`)}
              >
                Configure
              </Button>
            }
          >
            <ul className="list-disc space-y-1 pl-5 text-sm text-[var(--color-text-secondary)]">
              {s.description.map((d) => (
                <li key={d}>{d}</li>
              ))}
            </ul>
          </Panel>
        ))}
      </div>
    </div>
  )
}
