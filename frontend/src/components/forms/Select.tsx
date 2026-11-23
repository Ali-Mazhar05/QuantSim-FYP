import { useId } from 'react'

export interface SelectOption<T extends string> {
  value: T
  label: string
}

const FIELD =
  'rounded border border-[var(--color-border-control)] bg-[var(--color-bg-1)] px-3 py-1.5 text-sm text-[var(--color-text-primary)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--color-accent)]'

/** A labelled native select: reachable by keyboard and by its label for screen readers and tests. */
export default function Select<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string
  value: T
  options: SelectOption<T>[]
  onChange: (value: T) => void
}) {
  const id = useId()
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="text-xs font-medium uppercase tracking-wide text-[var(--color-text-muted)]">
        {label}
      </label>
      <select id={id} className={FIELD} value={value} onChange={(event) => onChange(event.target.value as T)}>
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </div>
  )
}
