import { useId } from 'react'
import { INPUT_CLASS } from './authShared'

/** A labelled POC input with an optional error line under it. */
export default function AuthField({
  label,
  value,
  onChange,
  type = 'text',
  error,
  autoComplete,
  className = 'mb-3',
}: {
  label: string
  value: string
  onChange: (value: string) => void
  type?: 'text' | 'email' | 'password'
  error?: string | null
  autoComplete?: string
  className?: string
}) {
  const errorId = useId()
  return (
    <label className={`${className} block`}>
      <span className="mb-1 block text-xs font-medium text-[var(--color-text-secondary)]">{label}</span>
      <input
        type={type}
        value={value}
        autoComplete={autoComplete}
        onChange={(e) => onChange(e.target.value)}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? errorId : undefined}
        className={INPUT_CLASS}
      />
      {error && (
        <span id={errorId} className="mt-1 block text-[11px] text-[var(--color-risk-severe)]">
          {error}
        </span>
      )}
    </label>
  )
}
