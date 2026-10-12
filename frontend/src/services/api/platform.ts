// Platform service calls: sign-in, sign-up and the emailed links, the signed-in user,
// sign-out and user accounts. The account routes are public and send no token.

import type { Role, UserAccount } from '../../types'
import { apiRequest, clearSession, publicRequest, refreshSession, setSession, storedRefreshToken } from './client'

export type ApiRole = 'viewer' | 'analyst' | 'quant' | 'admin'
export type AccountType = 'viewer' | 'analyst' | 'quant'

export const PROBLEM_EMAIL_UNVERIFIED = 'urn:quantsim:problem:email-unverified'
export const PROBLEM_APPROVAL_PENDING = 'urn:quantsim:problem:approval-pending'

interface ApiUser {
  id: string
  username: string
  email: string
  display_name: string
  role: ApiRole
  is_active: boolean
  status: 'active' | 'invited' | 'pending' | 'disabled'
  last_login_at: string | null
}

export interface SignedInUser {
  username: string
  name: string
  email: string
  role: Role
  capabilities: string[]
}

const BASE = '/api/platform'

const ROLE_NAMES: Record<ApiRole, Role> = { viewer: 'Viewer', analyst: 'Analyst', quant: 'Quant', admin: 'Admin' }
const STATUS_NAMES: Record<ApiUser['status'], UserAccount['status']> = {
  active: 'Active',
  invited: 'Invited',
  pending: 'Pending',
  disabled: 'Disabled',
}

/** The app's role name for an API role, or null when the value is not a known role. */
export function roleName(value: unknown): Role | null {
  return typeof value === 'string' && value in ROLE_NAMES ? ROLE_NAMES[value as ApiRole] : null
}

export function apiRole(role: Role): ApiRole {
  return role.toLowerCase() as ApiRole
}

async function me(): Promise<SignedInUser> {
  const user = await apiRequest<ApiUser & { capabilities: string[] }>(`${BASE}/auth/me`)
  return {
    username: user.username,
    name: user.display_name,
    email: user.email,
    role: ROLE_NAMES[user.role],
    capabilities: user.capabilities,
  }
}

/** Sign in with a username or an email; throws ApiUnreachableError when there is no backend. */
export async function signIn(username: string, password: string): Promise<SignedInUser> {
  const tokens = await publicRequest<{ access_token: string; refresh_token: string }>(
    `${BASE}/auth/login`,
    { username, password },
    5000,
  )
  setSession(tokens.access_token, tokens.refresh_token)
  return me()
}

/** Resume the session kept in this tab after a page reload, if it is still valid. */
export async function resumeSession(): Promise<SignedInUser | null> {
  if (!storedRefreshToken()) return null
  try {
    return (await refreshSession()) ? await me() : null
  } catch {
    return null
  }
}

/** End the session on the server too; the local copy is cleared whatever happens. */
export async function signOut(): Promise<void> {
  const token = storedRefreshToken()
  clearSession()
  if (!token) return
  try {
    await apiRequest(`${BASE}/auth/logout`, { method: 'POST', body: JSON.stringify({ refresh_token: token }) }, 3000)
  } catch {
    // the session expires on its own; nothing more to do
  }
}

// ---- Public account routes (no token) ----

export function signUp(input: {
  username: string
  email: string
  password: string
  account_type: AccountType
}): Promise<{ message: string }> {
  return publicRequest(`${BASE}/auth/signup`, input)
}

export function verifyEmail(token: string): Promise<{ status: 'verified'; approval_required: boolean }> {
  return publicRequest(`${BASE}/auth/verify-email`, { token })
}

export function resendVerification(email: string): Promise<{ message: string }> {
  return publicRequest(`${BASE}/auth/resend-verification`, { email })
}

export function forgotPassword(email: string): Promise<{ message: string }> {
  return publicRequest(`${BASE}/auth/forgot-password`, { email })
}

/** Set a password through an invitation or reset link. */
export function setPassword(token: string, password: string): Promise<{ status: 'password_set' }> {
  return publicRequest(`${BASE}/auth/reset-password`, { token, password })
}

// ---- User administration ----

function lastActive(value: string | null): string {
  if (!value) return '—'
  const date = new Date(value)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

function toUserAccount(u: ApiUser): UserAccount {
  return {
    id: u.id,
    name: u.display_name,
    email: u.email,
    role: ROLE_NAMES[u.role],
    status: STATUS_NAMES[u.status],
    lastActive: lastActive(u.last_login_at),
  }
}

/** Every account, shaped exactly like the POC Users page rows. */
export async function listUsers(): Promise<UserAccount[]> {
  const page = await apiRequest<{ items: ApiUser[] }>(`${BASE}/users?include_inactive=true&limit=200`)
  return page.items.map(toUserAccount)
}

/** Create an account by invitation: the user sets their own password from the email. */
export async function inviteUser(input: {
  username: string
  email: string
  displayName: string
  role: Role
}): Promise<UserAccount> {
  const user = await apiRequest<ApiUser>(`${BASE}/users`, {
    method: 'POST',
    body: JSON.stringify({
      username: input.username,
      email: input.email,
      display_name: input.displayName,
      role: apiRole(input.role),
    }),
  })
  return toUserAccount(user)
}

export async function approveUser(id: string): Promise<UserAccount> {
  return toUserAccount(await apiRequest<ApiUser>(`${BASE}/users/${encodeURIComponent(id)}/approve`, { method: 'POST' }))
}

export async function rejectUser(id: string): Promise<UserAccount> {
  return toUserAccount(await apiRequest<ApiUser>(`${BASE}/users/${encodeURIComponent(id)}/reject`, { method: 'POST' }))
}

export async function resendInvite(id: string): Promise<void> {
  await apiRequest(`${BASE}/users/${encodeURIComponent(id)}/resend-invite`, { method: 'POST' })
}

export async function changeRole(id: string, role: Role): Promise<UserAccount> {
  const user = await apiRequest<ApiUser>(`${BASE}/users/${encodeURIComponent(id)}/role`, {
    method: 'PUT',
    body: JSON.stringify({ role: apiRole(role) }),
  })
  return toUserAccount(user)
}
