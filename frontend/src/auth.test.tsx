import { fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useDemoStore } from './demo/demoState'
import { clearSession } from './services/api/client'
import { account, fakeBackend, json, problem, renderApp, unreachableBackend } from './test/fakeBackend'

const ACCOUNTS = {
  'sara.viewer': { role: 'viewer', capabilities: ['view_alerts', 'view_dashboards', 'view_market_data', 'view_reports'] },
  'ali.admin': { role: 'admin', capabilities: ['manage_users', 'manage_roles', 'configure_system'] },
} as const

function backend(username: keyof typeof ACCOUNTS) {
  return fakeBackend({
    'POST /auth/login': () => json(200, { access_token: 'a', refresh_token: 'r'.repeat(43) }),
    'GET /auth/me': () =>
      json(200, {
        id: '1',
        username,
        email: `${username}@quantsim.dev`,
        display_name: username === 'ali.admin' ? 'Ali Mazhar' : 'Sara Viewer',
        role: ACCOUNTS[username].role,
        capabilities: ACCOUNTS[username].capabilities,
        is_active: true,
        status: 'active',
        last_login_at: null,
      }),
    'POST /auth/logout': () => new Response(null, { status: 204 }),
  })
}

function submitSignIn(username: string, password = 'correct horse battery') {
  renderApp('/login')
  fireEvent.change(screen.getByLabelText('Username or email'), { target: { value: username } })
  fireEvent.change(screen.getByLabelText('Password'), { target: { value: password } })
  fireEvent.click(screen.getByRole('button', { name: 'Sign In' }))
}

describe('real sign-in and role-specific display', () => {
  beforeEach(() => {
    clearSession()
    useDemoStore.getState().logout()
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('shows the sign-in card with empty fields, links and no role picker', () => {
    renderApp('/login')
    expect(screen.getByLabelText('Username or email')).toHaveValue('')
    expect(screen.getByLabelText('Password')).toHaveValue('')
    expect(screen.getByRole('link', { name: 'Forgot password?' })).toHaveAttribute('href', '/forgot-password')
    expect(screen.getByRole('link', { name: 'Create account' })).toHaveAttribute('href', '/signup')
    expect(screen.queryByText('Demo as')).not.toBeInTheDocument()
    expect(screen.queryAllByRole('radio')).toHaveLength(0)
    expect(screen.queryByRole('button', { name: /^Admin/ })).not.toBeInTheDocument()
  })

  it('signs in for real and uses the account role', async () => {
    const { calls } = backend('sara.viewer')
    submitSignIn('sara.viewer')
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/dashboard'))
    const state = useDemoStore.getState()
    expect(state.authenticated).toBe(true)
    expect(state.role).toBe('Viewer')
    expect(state.account?.role).toBe('Viewer')
    expect(calls[0]).toMatchObject({ method: 'POST', path: '/auth/login', body: { username: 'sara.viewer' } })
  })

  it('stays on sign-in with a message when the server cannot be reached', async () => {
    unreachableBackend()
    submitSignIn('anyone')
    expect(await screen.findByText('Cannot reach the QuantSim server')).toBeInTheDocument()
    expect(screen.getByTestId('location')).toHaveTextContent('/login')
    expect(useDemoStore.getState().authenticated).toBe(false)
  })

  it('shows the platform message when the password is wrong', async () => {
    fakeBackend({
      'POST /auth/login': () =>
        problem(401, 'urn:quantsim:problem:invalid-credentials', 'The username or password is incorrect.'),
    })
    submitSignIn('ali.admin', 'wrong password')
    expect(await screen.findByText('The username or password is incorrect.')).toBeInTheDocument()
    expect(useDemoStore.getState().authenticated).toBe(false)
  })

  it('says how long to wait when the account is locked', async () => {
    fakeBackend({
      'POST /auth/login': () =>
        problem(429, 'urn:quantsim:problem:locked', 'Too many failed sign-ins.', { retry_after_seconds: 540 }),
    })
    submitSignIn('ali.admin')
    expect(await screen.findByText('Too many attempts, try again in 9 minutes')).toBeInTheDocument()
  })

  it('asks to verify the email first and resends the link to the given address', async () => {
    const { calls } = fakeBackend({
      'POST /auth/login': () => problem(403, 'urn:quantsim:problem:email-unverified', 'Verify your email first.'),
      'POST /auth/resend-verification': () => json(202, { message: 'sent' }),
    })
    submitSignIn('sara.k')
    expect(await screen.findByRole('heading', { name: 'Verify your email first' })).toBeInTheDocument()
    // A username was typed, so the page asks for the email
    fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'sara@example.com' } })
    fireEvent.click(screen.getByRole('button', { name: 'Send the link again' }))
    expect(await screen.findByText('If an account uses that email, we have sent a link.')).toBeInTheDocument()
    expect(calls.at(-1)).toMatchObject({ path: '/auth/resend-verification', body: { email: 'sara@example.com' } })
    expect(calls.at(-1)?.authorization).toBeNull()
  })

  it('uses the typed email for the resend without asking again', async () => {
    const { calls } = fakeBackend({
      'POST /auth/login': () => problem(403, 'urn:quantsim:problem:email-unverified', 'Verify your email first.'),
      'POST /auth/resend-verification': () => json(202, { message: 'sent' }),
    })
    submitSignIn('sara@example.com')
    await screen.findByRole('heading', { name: 'Verify your email first' })
    expect(screen.queryByLabelText('Email')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Send the link again' }))
    await waitFor(() => expect(calls.at(-1)?.body).toEqual({ email: 'sara@example.com' }))
  })

  it('shows the waiting screen naming the requested role', async () => {
    fakeBackend({
      'POST /auth/login': () =>
        problem(403, 'urn:quantsim:problem:approval-pending', 'Waiting for approval.', { requested_role: 'quant' }),
    })
    submitSignIn('sara.k')
    expect(await screen.findByRole('heading', { name: 'Waiting for admin approval' })).toBeInTheDocument()
    expect(screen.getByText('Quant')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Back to sign in' }))
    expect(screen.getByRole('button', { name: 'Sign In' })).toBeInTheDocument()
    expect(useDemoStore.getState().authenticated).toBe(false)
  })

  it('sends a visitor without a session from /dashboard to /login', () => {
    renderApp('/dashboard')
    expect(screen.getByTestId('location')).toHaveTextContent('/login')
    expect(screen.getByRole('button', { name: 'Sign In' })).toBeInTheDocument()
  })

  it('sends a signed-in visitor from /login to /dashboard', () => {
    useDemoStore.getState().startSession(account('Quant'))
    renderApp('/login')
    expect(screen.getByTestId('location')).toHaveTextContent('/dashboard')
  })

  it('never lets a signed-in account preview a higher role', () => {
    useDemoStore.getState().startSession(account('Quant'))
    useDemoStore.getState().setRole('Admin')
    expect(useDemoStore.getState().role).toBe('Quant')
    useDemoStore.getState().setRole('Viewer')
    expect(useDemoStore.getState().role).toBe('Viewer')
  })

  it('offers only equal or lower roles in the top bar preview', () => {
    useDemoStore.getState().startSession(account('Analyst'))
    renderApp('/dashboard')
    fireEvent.click(screen.getByRole('button', { name: 'Analyst' }))
    expect(screen.getByRole('button', { name: 'Preview as Viewer' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Preview as Analyst' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Preview as Quant' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Preview as Admin' })).not.toBeInTheDocument()
  })

  it('hides administration from a viewer and sends a viewer away from an admin URL', () => {
    useDemoStore.getState().startSession(account('Viewer'))
    renderApp('/admin/users')
    expect(screen.queryByText('Accounts provisioned for the Research Environment.')).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /Users/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /Stress Testing/ })).not.toBeInTheDocument()
  })

  it('shows administration to an admin', () => {
    useDemoStore.getState().startSession(account('Admin'))
    renderApp('/admin/system')
    expect(screen.getByText('Platform configuration and service health overview.')).toBeInTheDocument()
  })
})
