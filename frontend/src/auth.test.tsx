import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { useDemoStore } from './demo/demoState'
import { clearSession } from './services/api/client'

const ACCOUNTS = {
  'sara.viewer': { role: 'viewer', capabilities: ['view_alerts', 'view_dashboards', 'view_market_data', 'view_reports'] },
  'ali.admin': { role: 'admin', capabilities: ['manage_users', 'manage_roles', 'configure_system'] },
} as const

function backend(username: keyof typeof ACCOUNTS | null) {
  return vi.fn(async (url: string, init?: RequestInit) => {
    const path = new URL(url).pathname
    if (path.endsWith('/auth/login')) {
      if (!username) return new Response(JSON.stringify({ detail: 'The username or password is incorrect.' }), { status: 401 })
      return new Response(JSON.stringify({ access_token: 'a', refresh_token: 'r'.repeat(43) }), { status: 200 })
    }
    if (path.endsWith('/auth/me') && username) {
      const account = ACCOUNTS[username]
      return new Response(
        JSON.stringify({
          username,
          email: `${username}@quantsim.dev`,
          display_name: username === 'ali.admin' ? 'Ali Mazhar' : 'Sara Viewer',
          role: account.role,
          capabilities: account.capabilities,
          is_active: true,
          status: 'active',
          last_login_at: null,
          id: '1',
        }),
        { status: 200 },
      )
    }
    if (path.endsWith('/auth/logout')) return new Response(null, { status: 204 })
    void init
    return new Response('{}', { status: 404 })
  })
}

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  )
}

async function signInAs(username: string, pickRole = 'Admin') {
  renderAt('/login')
  fireEvent.change(screen.getAllByRole('textbox')[0], { target: { value: username } })
  fireEvent.click(screen.getByRole('button', { name: new RegExp(`^${pickRole}`) }))
  fireEvent.click(screen.getByRole('button', { name: 'Sign In' }))
}

describe('real sign-in and role-specific display', () => {
  beforeEach(() => {
    clearSession()
    useDemoStore.getState().logout()
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('signs in for real and uses the account role, not a higher picked one', async () => {
    vi.stubGlobal('fetch', backend('sara.viewer'))
    await signInAs('sara.viewer', 'Admin')
    await waitFor(() => expect(useDemoStore.getState().authenticated).toBe(true))
    const state = useDemoStore.getState()
    expect(state.mode).toBe('live')
    expect(state.role).toBe('Viewer')
    expect(state.account?.role).toBe('Viewer')
  })

  it('never lets a signed-in account preview a higher role', () => {
    useDemoStore.getState().signInLive(
      { username: 'q', name: 'Q', email: 'q@x', role: 'Quant', capabilities: [] },
      'Quant',
    )
    useDemoStore.getState().setRole('Admin')
    expect(useDemoStore.getState().role).toBe('Quant')
    useDemoStore.getState().setRole('Viewer')
    expect(useDemoStore.getState().role).toBe('Viewer')
  })

  it('falls back to demo mode when no backend is reachable', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => Promise.reject(new TypeError('Failed to fetch'))))
    await signInAs('anyone', 'Analyst')
    await waitFor(() => expect(useDemoStore.getState().authenticated).toBe(true))
    expect(useDemoStore.getState().mode).toBe('demo')
    expect(useDemoStore.getState().role).toBe('Analyst')
  })

  it('stays on the sign-in page when the password is wrong', async () => {
    vi.stubGlobal('fetch', backend(null))
    await signInAs('ali.admin')
    await waitFor(() => expect(screen.getByRole('button', { name: 'Sign In' })).not.toBeDisabled())
    expect(useDemoStore.getState().authenticated).toBe(false)
  })

  it('hides administration from a viewer and sends a viewer away from an admin URL', () => {
    useDemoStore.getState().signInLive(
      { username: 'v', name: 'V', email: 'v@x', role: 'Viewer', capabilities: [] },
      'Viewer',
    )
    renderAt('/admin/users')
    expect(screen.queryByText('Accounts provisioned for the Research Environment.')).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /Users/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /Stress Testing/ })).not.toBeInTheDocument()
  })

  it('shows administration to an admin', () => {
    useDemoStore.getState().signInLive(
      { username: 'a', name: 'A', email: 'a@x', role: 'Admin', capabilities: [] },
      'Admin',
    )
    renderAt('/admin/system')
    expect(screen.getByText('Platform configuration and service health overview.')).toBeInTheDocument()
  })
})
