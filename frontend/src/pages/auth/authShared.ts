// Constants and helpers shared by the sign-in, sign-up and emailed-link pages.

import { ApiError, ApiUnreachableError } from '../../services/api/client'
import type { Role } from '../../types'

/** The POC sign-in card's role descriptions. */
export const ROLE_OPTIONS: { role: Role; description: string }[] = [
  { role: 'Viewer', description: 'View dashboards, reports & alerts' },
  { role: 'Analyst', description: 'Run stress tests & TDA analysis' },
  { role: 'Quant', description: 'Launch simulations & build portfolios' },
  { role: 'Admin', description: 'Manage users, roles & system' },
]

/** The POC text input. */
export const INPUT_CLASS =
  'w-full rounded border border-[var(--color-border-strong)] bg-[var(--color-bg-2)] px-3 py-2 text-sm text-[var(--color-text-primary)] focus:border-[var(--color-accent-strong)] focus:outline-none'

export const LINK_CLASS = 'font-medium text-[var(--color-accent-strong)] hover:underline'

export const UNREACHABLE_MESSAGE = 'Cannot reach the QuantSim server'
export const SENT_MESSAGE = 'If an account uses that email, we have sent a link.'
export const INVALID_LINK_MESSAGE = 'This link is invalid or has expired.'

const USERNAME_PATTERN = /^[a-z0-9._-]{3,40}$/
const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

export function usernameProblem(username: string): string | null {
  return USERNAME_PATTERN.test(username.trim().toLowerCase())
    ? null
    : 'Use 3-40 characters: letters, digits, dot, underscore or hyphen.'
}

export function emailProblem(email: string): string | null {
  return EMAIL_PATTERN.test(email.trim()) ? null : 'Enter a valid email address.'
}

export function passwordProblem(password: string): string | null {
  return password.length >= 12 && password.length <= 1024 ? null : 'Use 12 to 1024 characters.'
}

/** Field problems of a password pair; empty when it may be sent. */
export function passwordPairProblems(password: string, confirm: string): { password?: string; confirm?: string } {
  const problem = passwordProblem(password)
  if (problem) return { password: problem }
  if (password !== confirm) return { confirm: 'Passwords do not match' }
  return {}
}

export function tryAgainMessage(error: ApiError): string {
  const minutes = Math.max(1, Math.ceil((error.retryAfterSeconds ?? 60) / 60))
  return `Too many attempts, try again in ${minutes} minute${minutes === 1 ? '' : 's'}`
}

/** A message for a failed public call: unreachable, rate limited, or the API's own detail. */
export function errorMessage(error: unknown): string {
  if (error instanceof ApiUnreachableError) return UNREACHABLE_MESSAGE
  if (error instanceof ApiError) return error.status === 429 ? tryAgainMessage(error) : error.message
  return 'Something went wrong, please try again.'
}

/** The emailed link's parameters, carried in the `#` fragment so no server ever logs them. */
export function readHashParams(): URLSearchParams {
  return new URLSearchParams(window.location.hash.replace(/^#/, ''))
}

/** Take the fragment out of the address bar, so the token is not kept in the history. */
export function clearHash(): void {
  if (window.location.hash) {
    window.history.replaceState(window.history.state, '', window.location.pathname + window.location.search)
  }
}
