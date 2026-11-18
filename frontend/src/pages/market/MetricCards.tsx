import KpiCard from '../../components/status/KpiCard'
import type { Metrics } from '../../services/api/market'

type Key = 'period_return' | 'annualised_volatility' | 'max_drawdown'

/** A ratio as text: 0.1234 is "12.34%", with a sign when the direction matters. */
function percent(ratio: string, signed = false): string {
  const value = Number(ratio) * 100
  return `${signed && value > 0 ? '+' : ''}${value.toFixed(2)}%`
}

const tone = (ratio: string | null) =>
  ratio === null || Number(ratio) === 0 ? 'neutral' : Number(ratio) > 0 ? 'positive' : 'negative'

/**
 * Period return, annualised volatility, maximum drawdown and the number of observations for the
 * window on screen. A metric the API could not compute says why, in words.
 */
export default function MetricCards({
  metrics,
  loading,
  error,
}: {
  metrics: Metrics | undefined
  loading: boolean
  error: string | null
}) {
  const card = (key: Key, label: string, signed: boolean, extra?: string) => {
    const value = metrics?.[key] ?? null
    if (value !== null) {
      return (
        <KpiCard
          label={label}
          value={percent(value, signed)}
          valueTone={signed ? tone(value) : 'neutral'}
          hint={extra}
        />
      )
    }
    const reason = loading ? 'Loading' : (metrics?.unavailable[key] ?? error ?? 'No data for this window')
    return <KpiCard label={label} value={loading ? '…' : 'Unavailable'} hint={reason} />
  }
  const drawdown =
    metrics?.max_drawdown != null && metrics.drawdown_peak && metrics.drawdown_trough
      ? `Peak ${metrics.drawdown_peak}, trough ${metrics.drawdown_trough}`
      : undefined
  return (
    <section aria-label="Metrics for the window shown" className="grid grid-cols-2 gap-4 lg:grid-cols-4">
      {card('period_return', 'Period return', true)}
      {card('annualised_volatility', 'Annualised volatility', false)}
      {card('max_drawdown', 'Max drawdown', false, drawdown)}
      <KpiCard
        label="Observations"
        value={metrics ? metrics.observations : loading ? '…' : '—'}
        hint={metrics ? `Prices: ${metrics.price_basis.replace('_', ' ')}` : undefined}
      />
    </section>
  )
}
