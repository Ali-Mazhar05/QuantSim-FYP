import clsx from 'clsx'
import { Radar } from 'lucide-react'
import type { FormEvent, ReactNode } from 'react'

/** The POC sign-in layout: logo, title and subtitle above a qs-panel card. */
export default function AuthCard({
  title = 'QuantSim',
  subtitle,
  onSubmit,
  children,
}: {
  title?: string
  subtitle?: ReactNode
  onSubmit?: (e: FormEvent<HTMLFormElement>) => void
  children: ReactNode
}) {
  const body = (
    <>
      {children}
      <div className="mt-4 text-center text-xs text-[var(--color-text-muted)]">Research Environment</div>
    </>
  )
  return (
    <div className="flex min-h-screen items-center justify-center bg-[var(--color-bg-0)] px-4">
      <div className="w-full max-w-md">
        <div className="mb-8 flex flex-col items-center text-center">
          <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-lg bg-[var(--color-accent)]/15 text-[var(--color-accent-strong)]">
            <Radar size={24} />
          </div>
          <h1 className="text-2xl font-semibold tracking-tight text-[var(--color-text-primary)]">{title}</h1>
          <p className="mt-2 text-sm text-[var(--color-text-secondary)]">
            {subtitle ?? (
              <>
                AI-Assisted Market Simulation
                <br />
                &amp; Portfolio Risk Analytics
              </>
            )}
          </p>
        </div>

        {onSubmit ? (
          <form onSubmit={onSubmit} noValidate className="qs-panel rounded p-6">
            {body}
          </form>
        ) : (
          <div className="qs-panel rounded p-6">{body}</div>
        )}
      </div>
    </div>
  )
}

// The StatusPill tone colours, as a block inside the card
const NOTICE_TONES = {
  warning: 'text-[var(--color-risk-elevated)] border-[var(--color-risk-elevated)]/70 bg-[var(--color-risk-elevated)]/10',
  success: 'text-[var(--color-risk-low)] border-[var(--color-risk-low)]/70 bg-[var(--color-risk-low)]/10',
  info: 'text-[var(--color-info)] border-[var(--color-info)]/70 bg-[var(--color-info)]/10',
}

/** An inline notice inside the card, in the POC badge colours. */
export function AuthNotice({ tone = 'warning', children }: { tone?: keyof typeof NOTICE_TONES; children: ReactNode }) {
  return (
    <div
      role={tone === 'warning' ? 'alert' : 'status'}
      className={clsx('mb-4 rounded border px-3 py-2 text-xs leading-relaxed', NOTICE_TONES[tone])}
    >
      {children}
    </div>
  )
}
