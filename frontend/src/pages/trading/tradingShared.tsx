// The loading, error and 403 states the five trading pages share (A-NFR-17).

import { Lock } from 'lucide-react'
import EmptyState from '../../components/status/EmptyState'
import type { Failure } from './tradingFormat'

export function Loading({ what }: { what: string }) {
  return (
    <p className="text-sm text-[var(--color-text-muted)]" data-testid="loading">
      Loading {what}…
    </p>
  )
}

export function ErrorNotice({ message }: { message: string }) {
  return (
    <p role="alert" className="text-sm text-[var(--color-risk-severe)]">
      {message}
    </p>
  )
}

export function Forbidden({ message }: { message: string }) {
  return (
    <div data-testid="forbidden">
      <EmptyState icon={Lock} title="Your role cannot open this" description={message} />
    </div>
  )
}

/** The failure as the page shows it: the 403 state or an error notice. */
export function FailureState({ failure }: { failure: Failure }) {
  return failure.forbidden ? <Forbidden message={failure.message} /> : <ErrorNotice message={failure.message} />
}
