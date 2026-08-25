import { Plus, Save, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import Button from '../../components/forms/Button'
import Panel from '../../components/layout/Panel'
import PageHeader from '../../components/layout/PageHeader'
import { useNotifications } from '../../demo/notifications'
import { STRATEGIES } from '../../services/mock/data'

const REBALANCE_OPTIONS = ['Daily', 'Weekly', 'Monthly'] as const

export default function ConfigureStrategy() {
  const { id } = useParams()
  const navigate = useNavigate()
  const push = useNotifications((s) => s.push)

  const existing = STRATEGIES.find((s) => s.id === id)
  const isNew = !existing

  const [name, setName] = useState(existing?.name ?? '')
  const [rebalance, setRebalance] = useState<(typeof REBALANCE_OPTIONS)[number]>(
    (existing?.rebalance as (typeof REBALANCE_OPTIONS)[number]) ?? 'Weekly',
  )
  const [maxPosition, setMaxPosition] = useState(existing?.maxPosition ?? 25)
  const [rules, setRules] = useState<string[]>(existing?.description ?? ['Buy assets with positive 20-day momentum.'])

  const updateRule = (i: number, value: string) => {
    setRules((r) => r.map((x, idx) => (idx === i ? value : x)))
  }
  const addRule = () => setRules((r) => [...r, ''])
  const removeRule = (i: number) => setRules((r) => r.filter((_, idx) => idx !== i))

  const save = () => {
    push(isNew ? 'Strategy created' : 'Strategy saved', 'success')
    navigate('/trading/strategies')
  }

  return (
    <div className="qs-fade-in flex flex-col gap-6">
      <PageHeader
        title={isNew ? 'New Strategy' : `Configure — ${existing.name}`}
        description="Define the entry rules, rebalance cadence and position limits for this strategy."
        breadcrumbs={[{ label: 'Strategies', to: '/trading/strategies' }, { label: isNew ? 'New' : existing.name }]}
      />

      <Panel title="Strategy Details">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <label className="flex flex-col gap-1.5">
            <span className="text-xs font-medium text-[var(--color-text-secondary)]">Strategy Name</span>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Low Volatility Rotation"
              className="rounded border border-[var(--color-border-strong)] bg-[var(--color-bg-2)] px-3 py-1.5 text-sm text-[var(--color-text-primary)] focus:border-[var(--color-accent)] focus:outline-none"
            />
          </label>
          <label className="flex flex-col gap-1.5">
            <span className="text-xs font-medium text-[var(--color-text-secondary)]">Rebalance Frequency</span>
            <select
              value={rebalance}
              onChange={(e) => setRebalance(e.target.value as (typeof REBALANCE_OPTIONS)[number])}
              className="rounded border border-[var(--color-border-strong)] bg-[var(--color-bg-2)] px-3 py-1.5 text-sm text-[var(--color-text-primary)] focus:border-[var(--color-accent)] focus:outline-none"
            >
              {REBALANCE_OPTIONS.map((o) => (
                <option key={o} value={o}>
                  {o}
                </option>
              ))}
            </select>
          </label>
        </div>

        <label className="mt-4 flex flex-col gap-1.5">
          <span className="text-xs font-medium text-[var(--color-text-secondary)]">
            Maximum Position <span className="mono text-[var(--color-text-primary)]">{maxPosition}%</span>
          </span>
          <input
            type="range"
            min={5}
            max={50}
            step={5}
            value={maxPosition}
            onChange={(e) => setMaxPosition(Number(e.target.value))}
            className="accent-[var(--color-accent)]"
          />
        </label>
      </Panel>

      <Panel title="Entry Rules" subtitle="Plain-language rules used to construct the strategy description.">
        <div className="flex flex-col gap-2.5">
          {rules.map((r, i) => (
            <div key={i} className="flex items-center gap-2">
              <input
                value={r}
                onChange={(e) => updateRule(i, e.target.value)}
                placeholder="Describe a rule…"
                className="flex-1 rounded border border-[var(--color-border-strong)] bg-[var(--color-bg-2)] px-3 py-1.5 text-sm text-[var(--color-text-primary)] focus:border-[var(--color-accent)] focus:outline-none"
              />
              <button
                onClick={() => removeRule(i)}
                className="rounded p-1.5 text-[var(--color-text-muted)] hover:bg-white/5 hover:text-[var(--color-risk-severe)]"
                aria-label="Remove rule"
              >
                <Trash2 size={14} />
              </button>
            </div>
          ))}
        </div>
        <Button variant="secondary" size="sm" icon={Plus} className="mt-3" onClick={addRule}>
          Add Rule
        </Button>
      </Panel>

      <div className="flex justify-end gap-2">
        <Button variant="secondary" onClick={() => navigate('/trading/strategies')}>
          Cancel
        </Button>
        <Button icon={Save} onClick={save} disabled={!name.trim()}>
          {isNew ? 'Create Strategy' : 'Save Changes'}
        </Button>
      </div>
    </div>
  )
}
