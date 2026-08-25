import clsx from 'clsx'
import type { LucideIcon } from 'lucide-react'
import { Loader2 } from 'lucide-react'
import type { ButtonHTMLAttributes } from 'react'

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger'
  size?: 'sm' | 'md'
  icon?: LucideIcon
  loading?: boolean
}

export default function Button({
  variant = 'primary',
  size = 'md',
  icon: Icon,
  loading,
  className,
  children,
  disabled,
  ...rest
}: Props) {
  return (
    <button
      disabled={disabled || loading}
      className={clsx(
        'inline-flex items-center justify-center gap-2 rounded font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-40',
        size === 'sm' && 'px-2.5 py-1.5 text-xs',
        size === 'md' && 'px-4 py-2 text-sm',
        variant === 'primary' && 'bg-[var(--color-accent)] text-black hover:bg-[var(--color-accent-strong)]',
        variant === 'secondary' &&
          'border border-[var(--color-border-strong)] bg-[var(--color-bg-2)] text-[var(--color-text-primary)] hover:border-[var(--color-accent)]',
        variant === 'ghost' && 'text-[var(--color-text-secondary)] hover:bg-black/5 hover:text-[var(--color-text-primary)]',
        variant === 'danger' && 'bg-[var(--color-risk-severe)] text-white hover:brightness-110',
        className,
      )}
      {...rest}
    >
      {loading ? <Loader2 size={14} className="animate-spin" /> : Icon && <Icon size={14} />}
      {children}
    </button>
  )
}
