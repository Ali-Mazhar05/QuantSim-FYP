import { Plus, Settings2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Button from '../../components/forms/Button'
import { useCan } from '../../demo/useCan'
import Panel from '../../components/layout/Panel'
import PageHeader from '../../components/layout/PageHeader'
import EmptyState from '../../components/status/EmptyState'
import { type Strategy, listStrategies } from './tradingApi'
import { type Failure, failureOf, strategyRules, strategySubtitle } from './tradingFormat'
import { FailureState, Loading } from './tradingShared'

export default function Strategies() {
  const navigate = useNavigate()
  const canEdit = useCan('create_strategies')
  const [strategies, setStrategies] = useState<Strategy[] | null>(null)
  const [failure, setFailure] = useState<Failure | null>(null)

  useEffect(() => {
    let cancelled = false
    listStrategies()
      .then((rows) => !cancelled && setStrategies(rows))
      .catch((error: unknown) => !cancelled && setFailure(failureOf(error)))
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <div className="qs-fade-in flex flex-col gap-6">
      <PageHeader
        title="Strategies"
        description="Trading strategies available for portfolio construction. Select one to configure its rules."
        action={
          <Button icon={Plus} disabled={!canEdit} title={canEdit ? undefined : "Your role cannot do this"} onClick={() => navigate('/trading/strategies/new')}>
            New Strategy
          </Button>
        }
      />
      {failure ? (
        <FailureState failure={failure} />
      ) : strategies === null ? (
        <Loading what="strategies" />
      ) : strategies.length === 0 ? (
        <EmptyState
          title="No strategies yet"
          description={canEdit ? 'Create the first strategy with New Strategy.' : 'A quant or an administrator creates strategies.'}
        />
      ) : (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2" data-testid="strategy-list">
          {strategies.map((s) => (
            <div key={s.id} data-testid="strategy-card" data-strategy-id={s.id}>
              <Panel
                title={s.name}
                subtitle={strategySubtitle(s)}
                action={
                  <Button
                    variant="secondary"
                    size="sm"
                    icon={Settings2}
                    disabled={!canEdit}
                    onClick={() => navigate(`/trading/strategies/${s.id}`)}
                  >
                    Configure
                  </Button>
                }
              >
                <ul className="list-disc space-y-1 pl-5 text-sm text-[var(--color-text-secondary)]">
                  {strategyRules(s).map((d) => (
                    <li key={d}>{d}</li>
                  ))}
                </ul>
              </Panel>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
