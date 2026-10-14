import clsx from 'clsx'
import type { Role } from '../../types'

/** The POC sign-in card's two-column role buttons. */
export default function RoleGrid({
  label,
  roles,
  value,
  onChange,
}: {
  label: string
  roles: { role: Role; description: string }[]
  value: Role
  onChange: (role: Role) => void
}) {
  return (
    <div role="radiogroup" aria-label={label}>
      <span className="mb-2 block text-xs font-medium text-[var(--color-text-secondary)]">{label}</span>
      <div className="grid grid-cols-2 gap-2">
        {roles.map((r) => (
          <button
            type="button"
            role="radio"
            aria-checked={value === r.role}
            key={r.role}
            onClick={() => onChange(r.role)}
            className={clsx(
              'rounded border px-3 py-2 text-left transition-colors',
              value === r.role
                ? 'border-[var(--color-accent-strong)] bg-[var(--color-accent)]/10'
                : 'border-[var(--color-border-strong)] hover:border-[var(--color-border-strong)]/80',
            )}
          >
            <div
              className={clsx(
                'text-xs font-semibold',
                value === r.role ? 'text-[var(--color-accent-strong)]' : 'text-[var(--color-text-primary)]',
              )}
            >
              {r.role}
            </div>
            <div className="mt-0.5 text-[10px] leading-snug text-[var(--color-text-muted)]">{r.description}</div>
          </button>
        ))}
      </div>
    </div>
  )
}
