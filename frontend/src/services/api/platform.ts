// Platform service calls: sign-in, the signed-in user, sign-out and user accounts.

import type { Role, UserAccount } from '../../types'
import { apiRequest, clearSession, refreshSession, setSession, storedRefreshToken } from './client'

type ApiRole = 'viewer' | 'analyst' | 'quant' | 'admin'

interface ApiUser {
  id: string
  username: string
  email: string
  display_name: string
  role: ApiRole
  is_active: boolean
  status: 'active' | 'invited' | 'disabled'
  last_login_at: string | null
}

export interface SignedInUser {
  username: string
  name: string
  email: string
  role: Role
  capabilities: string[]
}

const ROLE_NAMES: Record<ApiRole, Role> = { viewer: 'Viewer', analyst: 'Analyst', quant: 'Quant', admin: 'Admin' }
const STATUS_NAMES: Record<ApiUser['status'], UserAccount['status']> = {
  active: 'Active',
  invited: 'Invited',
  disabled: 'Disabled',
}

async function me(): Promise<SignedInUser> {
  const user = await apiRequest<ApiUser & { capabilities: string[] }>('/api/platform/auth/me')
  return {
    username: user.username,
    name: user.display_name,
    email: user.email,
    role: ROLE_NAMES[user.role],
    capabilities: user.capabilities,
  }
}

/** Sign in for real; throws ApiUnreachableError when there is no backend to talk to. */
export async function signIn(username: string, password: string): Promise<SignedInUser> {
  const tokens = await apiRequest<{ access_token: string; refresh_token: string }>(
    '/api/platform/auth/login',
    { method: 'POST', body: JSON.stringify({ username, password }) },
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
    await apiRequest('/api/platform/auth/logout', { method: 'POST', body: JSON.stringify({ refresh_token: token }) }, 3000)
  } catch {
    // the session expires on its own; nothing more to do
  }
}

function lastActive(value: string | null): string {
  if (!value) return '—'
  const date = new Date(value)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

/** Every account, shaped exactly like the POC Users page rows. */
export async function listUsers(): Promise<UserAccount[]> {
  const page = await apiRequest<{ items: ApiUser[] }>('/api/platform/users?include_inactive=true&limit=200')
  return page.items.map((u) => ({
    id: u.id,
    name: u.display_name,
    email: u.email,
    role: ROLE_NAMES[u.role],
    status: STATUS_NAMES[u.status],
    lastActive: lastActive(u.last_login_at),
  }))
}
