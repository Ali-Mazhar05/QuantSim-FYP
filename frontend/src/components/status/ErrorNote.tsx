import type { ClassifiedError } from '../../hooks/apiError'

/** A failed read, in words: the 403 says the role may not, never only a colour (B-NFR-15). */
export default function ErrorNote({ error }: { error: ClassifiedError }) {
  return (
    <p role="alert" data-testid="error-note" data-kind={error.kind} className="text-sm text-[var(--color-risk-severe)]">
      {error.kind === 'forbidden' ? `Not allowed: ${error.message}` : error.message}
    </p>
  )
}
