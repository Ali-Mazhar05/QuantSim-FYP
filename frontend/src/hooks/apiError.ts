import { ApiError, ApiUnreachableError } from '../services/api/client'
import { errorMessage } from '../pages/auth/authShared'

export type ErrorKind =
  | 'unreachable'
  | 'unauthenticated' // 401, after the session refresh already failed
  | 'forbidden' // 403: the role may not do this; show the 403 state, never a retry
  | 'not_found' // 404
  | 'conflict' // 409
  | 'invalid' // 422: fieldErrors names the fields
  | 'rate_limited' // 429: retryAfterSeconds when the server said
  | 'server' // 5xx
  | 'unknown'

export interface ClassifiedError {
  kind: ErrorKind
  /** What to show the user. */
  message: string
  status: number | null
  retryAfterSeconds: number | null
  fieldErrors: Record<string, string>
}

const BY_STATUS: Record<number, ErrorKind> = {
  401: 'unauthenticated',
  403: 'forbidden',
  404: 'not_found',
  409: 'conflict',
  422: 'invalid',
  429: 'rate_limited',
}

/** One mapping from a failed call to what a page shows, so every page handles errors alike. */
export function classifyError(error: unknown): ClassifiedError {
  const message = errorMessage(error)
  if (error instanceof ApiUnreachableError) {
    return { kind: 'unreachable', message, status: null, retryAfterSeconds: null, fieldErrors: {} }
  }
  if (error instanceof ApiError) {
    const kind = BY_STATUS[error.status] ?? (error.status >= 500 ? 'server' : 'unknown')
    return {
      kind,
      message,
      status: error.status,
      retryAfterSeconds: error.retryAfterSeconds,
      fieldErrors: kind === 'invalid' ? error.fieldErrors : {},
    }
  }
  return { kind: 'unknown', message, status: null, retryAfterSeconds: null, fieldErrors: {} }
}

export const isForbidden = (error: unknown): boolean => classifyError(error).kind === 'forbidden'
