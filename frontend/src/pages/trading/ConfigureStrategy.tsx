import { Plus, Save, Trash2 } from 'lucide-react'
import { type ReactNode, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import Button from '../../components/forms/Button'
import Panel from '../../components/layout/Panel'
import PageHeader from '../../components/layout/PageHeader'
import EmptyState from '../../components/status/EmptyState'
import { useNotifications } from '../../demo/notifications'
import { ApiError } from '../../services/api/client'
import {
  STRATEGY_KINDS,
  type Strategy,
  type StrategyKind,
  type StrategyParams,
  createStrategy,
  getStrategy,
  isId,
  replaceStrategy,
} from './tradingApi'
import { type Failure, failureOf } from './tradingFormat'
import { ErrorNotice, FailureState, Loading } from './tradingShared'

// The prototype's Rebalance Frequency choices, in sessions (momentum's rebalance_every)
const REBALANCE_OPTIONS = [
  { label: 'Daily', sessions: 1 },
  { label: 'Weekly', sessions: 5 },
  { label: 'Monthly', sessions: 21 },
] as const

interface ParamField {
  key: string
  label: string
  /** Whole numbers go to the API as numbers, decimals as strings. */
  whole: boolean
  initial: string
}

// Mirrors the parameter models of services/trading (domain/strategies): rebalance_every
// and max_position of momentum sit in the Strategy Details panel, where the prototype
// had its rebalance and position controls; buy and hold's weights are the rule rows.
const KIND_FIELDS: Record<StrategyKind, ParamField[]> = {
  buy_and_hold: [],
  momentum: [
    { key: 'lookback', label: 'Lookback (sessions)', whole: true, initial: '60' },
    { key: 'top_n', label: 'Symbols Held (top N)', whole: true, initial: '3' },
  ],
  ma_crossover: [
    { key: 'fast', label: 'Fast Average (sessions)', whole: true, initial: '20' },
    { key: 'slow', label: 'Slow Average (sessions)', whole: true, initial: '50' },
  ],
  mean_reversion: [
    { key: 'window', label: 'Window (sessions)', whole: true, initial: '20' },
    { key: 'entry_z', label: 'Entry Z-Score', whole: false, initial: '2' },
    { key: 'exit_z', label: 'Exit Z-Score', whole: false, initial: '0' },
  ],
}
const CASH_BUFFER: ParamField = { key: 'cash_buffer', label: 'Cash Buffer (fraction)', whole: false, initial: '0.02' }
const MOMENTUM_DETAILS = { rebalance_every: '5', max_position: '0.25' }

interface WeightRow {
  symbol: string
  weight: string
}

interface Form {
  name: string
  kind: StrategyKind
  /** Every parameter as typed, by key. */
  values: Record<string, string>
  weights: WeightRow[]
}

function defaults(kind: StrategyKind): Record<string, string> {
  const values: Record<string, string> = { [CASH_BUFFER.key]: CASH_BUFFER.initial }
  for (const field of KIND_FIELDS[kind]) values[field.key] = field.initial
  if (kind === 'momentum') Object.assign(values, MOMENTUM_DETAILS)
  return values
}

function formOf(s: Strategy): Form {
  const kind = (STRATEGY_KINDS.some((k) => k.kind === s.kind) ? s.kind : 'momentum') as StrategyKind
  const values = defaults(kind)
  for (const [key, value] of Object.entries(s.params)) {
    if (key !== 'weights' && value !== null && value !== undefined) values[key] = String(value)
  }
  const weights = s.params.weights as Record<string, unknown> | null | undefined
  return {
    name: s.name,
    kind,
    values,
    weights: weights ? Object.entries(weights).map(([symbol, weight]) => ({ symbol, weight: String(weight) })) : [],
  }
}

function paramsOf(form: Form): StrategyParams {
  const wholeKeys = new Set([...KIND_FIELDS[form.kind].filter((f) => f.whole).map((f) => f.key), 'rebalance_every'])
  const params: StrategyParams = {}
  for (const [key, raw] of Object.entries(form.values)) {
    const text = raw.trim()
    // A whole number the user typed goes as a number; anything else is sent as typed so
    // the API's 422 names the field
    params[key] = wholeKeys.has(key) && /^-?\d+$/.test(text) ? Number(text) : text
  }
  if (form.kind === 'buy_and_hold' && form.weights.length > 0) {
    params.weights = Object.fromEntries(form.weights.map((w) => [w.symbol.trim(), w.weight.trim()]))
  }
  return params
}

/** Field name -> message from a 422: a parameter by its own name, otherwise the body field. */
function fieldErrorsOf(error: ApiError): Record<string, string> {
  const result: Record<string, string> = {}
  const errors = Array.isArray(error.body.errors) ? (error.body.errors as { location?: unknown[]; message?: unknown }[]) : []
  for (const entry of errors) {
    const location = Array.isArray(entry.location) ? entry.location : []
    const field = location[1] === 'params' && location.length > 2 ? String(location[2]) : String(location[1] ?? 'body')
    if (typeof entry.message === 'string' && !(field in result)) result[field] = entry.message
  }
  return result
}

const INPUT =
  'rounded border border-[var(--color-border-strong)] bg-[var(--color-bg-2)] px-3 py-1.5 text-sm text-[var(--color-text-primary)] focus:border-[var(--color-accent-strong)] focus:outline-none'

function Field({ label, error, field, children }: { label: ReactNode; error?: string; field: string; children: ReactNode }) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="text-xs font-medium text-[var(--color-text-secondary)]">{label}</span>
      {children}
      {error && (
        <span className="text-xs text-[var(--color-risk-severe)]" data-testid={`field-error-${field}`}>
          {error}
        </span>
      )}
    </label>
  )
}

export default function ConfigureStrategy() {
  const { id } = useParams()
  // Another strategy (or New) is a fresh form: nothing of the previous one carries over
  return <StrategyForm key={id ?? 'new'} id={id} />
}

function StrategyForm({ id }: { id: string | undefined }) {
  const navigate = useNavigate()
  const push = useNotifications((s) => s.push)
  const isNew = id === undefined

  const [existing, setExisting] = useState<Strategy | null>(null)
  const [missing, setMissing] = useState(!isNew && !isId(id))
  const [loadFailure, setLoadFailure] = useState<Failure | null>(null)
  const [form, setForm] = useState<Form>({ name: '', kind: 'momentum', values: defaults('momentum'), weights: [] })
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})
  const [saveError, setSaveError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (isNew || !isId(id)) return
    let cancelled = false
    getStrategy(id)
      .then((s) => {
        if (cancelled) return
        setExisting(s)
        setForm(formOf(s))
      })
      .catch((error: unknown) => {
        if (cancelled) return
        if (error instanceof ApiError && error.status === 404) setMissing(true)
        else setLoadFailure(failureOf(error))
      })
    return () => {
      cancelled = true
    }
  }, [id, isNew])

  const setValue = (key: string, value: string) => setForm((f) => ({ ...f, values: { ...f.values, [key]: value } }))
  const setKind = (kind: StrategyKind) => {
    setForm((f) => ({ ...f, kind, values: defaults(kind), weights: [] }))
    setFieldErrors({})
  }
  const updateWeight = (i: number, change: Partial<WeightRow>) =>
    setForm((f) => ({ ...f, weights: f.weights.map((w, idx) => (idx === i ? { ...w, ...change } : w)) }))
  const addWeight = () => setForm((f) => ({ ...f, weights: [...f.weights, { symbol: '', weight: '' }] }))
  const removeWeight = (i: number) => setForm((f) => ({ ...f, weights: f.weights.filter((_, idx) => idx !== i) }))

  const save = async () => {
    setSaving(true)
    setFieldErrors({})
    setSaveError(null)
    const input = { name: form.name.trim(), kind: form.kind, params: paramsOf(form) }
    try {
      if (existing) await replaceStrategy(existing.id, input)
      else await createStrategy(input)
      push(existing ? 'Strategy saved' : 'Strategy created', 'success')
      navigate('/trading/strategies')
    } catch (error: unknown) {
      if (error instanceof ApiError && error.status === 422) {
        const fields = fieldErrorsOf(error)
        setFieldErrors(fields)
        setSaveError(`Check ${Object.keys(fields).join(', ') || 'the form'}: ${error.message}`)
      } else {
        setSaveError(failureOf(error).message)
      }
    } finally {
      setSaving(false)
    }
  }

  if (missing) {
    return (
      <div className="qs-fade-in flex flex-col gap-6">
        <PageHeader title="Strategy not found" breadcrumbs={[{ label: 'Strategies', to: '/trading/strategies' }, { label: 'Not found' }]} />
        <EmptyState
          title="No strategy has this id"
          description="It may have been created in another environment. Pick one from the Strategies page."
          action={
            <Button variant="secondary" size="sm" onClick={() => navigate('/trading/strategies')}>
              Back to Strategies
            </Button>
          }
        />
      </div>
    )
  }

  const title = isNew ? 'New Strategy' : existing ? `Configure — ${existing.name}` : 'Configure Strategy'
  const loading = !isNew && !existing && !loadFailure
  const kindFields = [...KIND_FIELDS[form.kind], CASH_BUFFER]
  const rebalance = form.values.rebalance_every ?? ''
  const rebalanceOptions = REBALANCE_OPTIONS.some((o) => String(o.sessions) === rebalance)
    ? REBALANCE_OPTIONS
    : [...REBALANCE_OPTIONS, { label: `Every ${rebalance} sessions`, sessions: Number(rebalance) }]
  const maxPositionPct = Math.round(Number(form.values.max_position ?? '0') * 100)

  return (
    <div className="qs-fade-in flex flex-col gap-6">
      <PageHeader
        title={title}
        description="Define the entry rules, rebalance cadence and position limits for this strategy."
        breadcrumbs={[{ label: 'Strategies', to: '/trading/strategies' }, { label: isNew ? 'New' : (existing?.name ?? 'Configure') }]}
      />

      {loadFailure ? (
        <FailureState failure={loadFailure} />
      ) : loading ? (
        <Loading what="the strategy" />
      ) : (
        <>
          <Panel title="Strategy Details">
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <Field label="Strategy Name" error={fieldErrors.name} field="name">
                <input
                  value={form.name}
                  onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                  placeholder="e.g. Low Volatility Rotation"
                  className={INPUT}
                  data-testid="strategy-name"
                />
              </Field>
              <Field label="Strategy Type" error={fieldErrors.kind} field="kind">
                <select value={form.kind} onChange={(e) => setKind(e.target.value as StrategyKind)} className={INPUT} data-testid="strategy-kind">
                  {STRATEGY_KINDS.map((k) => (
                    <option key={k.kind} value={k.kind}>
                      {k.label}
                    </option>
                  ))}
                </select>
              </Field>
              {form.kind === 'momentum' && (
                <Field label="Rebalance Frequency" error={fieldErrors.rebalance_every} field="rebalance_every">
                  <select value={rebalance} onChange={(e) => setValue('rebalance_every', e.target.value)} className={INPUT}>
                    {rebalanceOptions.map((o) => (
                      <option key={o.label} value={String(o.sessions)}>
                        {o.label}
                      </option>
                    ))}
                  </select>
                </Field>
              )}
            </div>

            {form.kind === 'momentum' && (
              <label className="mt-4 flex flex-col gap-1.5">
                <span className="text-xs font-medium text-[var(--color-text-secondary)]">
                  Maximum Position <span className="mono text-[var(--color-text-primary)]">{maxPositionPct}%</span>
                </span>
                <input
                  type="range"
                  min={5}
                  max={100}
                  step={5}
                  value={maxPositionPct}
                  onChange={(e) => setValue('max_position', String(Number(e.target.value) / 100))}
                  className="accent-[var(--color-accent)]"
                />
                {fieldErrors.max_position && (
                  <span className="text-xs text-[var(--color-risk-severe)]" data-testid="field-error-max_position">
                    {fieldErrors.max_position}
                  </span>
                )}
              </label>
            )}
          </Panel>

          <Panel title="Entry Rules" subtitle="The parameters of the chosen strategy type; the server checks every value.">
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              {kindFields.map((f) => (
                <Field key={f.key} label={f.label} error={fieldErrors[f.key]} field={f.key}>
                  <input
                    value={form.values[f.key] ?? ''}
                    onChange={(e) => setValue(f.key, e.target.value)}
                    inputMode={f.whole ? 'numeric' : 'decimal'}
                    className={INPUT}
                    data-testid={`param-${f.key}`}
                  />
                </Field>
              ))}
            </div>
            {form.kind === 'buy_and_hold' && (
              <div className="mt-4">
                <div className="mb-2 text-xs text-[var(--color-text-muted)]">
                  Weights per symbol, as fractions of investable value. Leave empty to buy every symbol at equal weights.
                </div>
                <div className="flex flex-col gap-2.5">
                  {form.weights.map((w, i) => (
                    <div key={i} className="flex items-center gap-2">
                      <input
                        value={w.symbol}
                        onChange={(e) => updateWeight(i, { symbol: e.target.value })}
                        placeholder="Symbol"
                        aria-label={`Symbol ${i + 1}`}
                        className={`${INPUT} w-28`}
                      />
                      <input
                        value={w.weight}
                        onChange={(e) => updateWeight(i, { weight: e.target.value })}
                        placeholder="Weight, e.g. 0.5"
                        aria-label={`Weight ${i + 1}`}
                        inputMode="decimal"
                        className={`${INPUT} flex-1`}
                      />
                      <button
                        onClick={() => removeWeight(i)}
                        className="rounded p-1.5 text-[var(--color-text-muted)] hover:bg-black/5 hover:text-[var(--color-risk-severe)]"
                        aria-label="Remove rule"
                      >
                        <Trash2 size={14} />
                      </button>
                    </div>
                  ))}
                </div>
                {fieldErrors.weights && (
                  <div className="mt-2 text-xs text-[var(--color-risk-severe)]" data-testid="field-error-weights">
                    {fieldErrors.weights}
                  </div>
                )}
                <Button variant="secondary" size="sm" icon={Plus} className="mt-3" onClick={addWeight}>
                  Add Rule
                </Button>
              </div>
            )}
          </Panel>

          {saveError && <ErrorNotice message={saveError} />}

          <div className="flex justify-end gap-2">
            <Button variant="secondary" onClick={() => navigate('/trading/strategies')}>
              Cancel
            </Button>
            <Button icon={Save} onClick={() => void save()} disabled={!form.name.trim()} loading={saving}>
              {isNew ? 'Create Strategy' : 'Save Changes'}
            </Button>
          </div>
        </>
      )}
    </div>
  )
}
