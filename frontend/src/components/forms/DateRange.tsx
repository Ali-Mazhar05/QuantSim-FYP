import { useId } from 'react'
import { isInverted } from './dateWindow'

const FIELD =
  'rounded border border-[var(--color-border-control)] bg-[var(--color-bg-1)] px-3 py-1.5 text-sm text-[var(--color-text-primary)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--color-accent)] aria-[invalid=true]:border-[var(--color-risk-severe)]'
const LABEL = 'text-xs font-medium uppercase tracking-wide text-[var(--color-text-muted)]'

/**
 * A date window as two labelled date inputs. Empty means open on that side. An inverted window is
 * named in text next to the inputs, not only by colour.
 */
export default function DateRange({
  from,
  to,
  onChange,
}: {
  from: string
  to: string
  onChange: (range: { from: string; to: string }) => void
}) {
  const fromId = useId()
  const toId = useId()
  const messageId = useId()
  const inverted = isInverted(from, to)
  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-end gap-2">
        <div className="flex flex-col gap-1">
          <label htmlFor={fromId} className={LABEL}>
            From
          </label>
          <input
            id={fromId}
            type="date"
            className={FIELD}
            value={from}
            max={to || undefined}
            aria-invalid={inverted}
            aria-describedby={inverted ? messageId : undefined}
            onChange={(event) => onChange({ from: event.target.value, to })}
          />
        </div>
        <div className="flex flex-col gap-1">
          <label htmlFor={toId} className={LABEL}>
            To
          </label>
          <input
            id={toId}
            type="date"
            className={FIELD}
            value={to}
            min={from || undefined}
            aria-invalid={inverted}
            aria-describedby={inverted ? messageId : undefined}
            onChange={(event) => onChange({ from, to: event.target.value })}
          />
        </div>
      </div>
      {inverted && (
        <p id={messageId} role="alert" className="text-xs text-[var(--color-risk-severe)]">
          From must not be after To.
        </p>
      )}
    </div>
  )
}
