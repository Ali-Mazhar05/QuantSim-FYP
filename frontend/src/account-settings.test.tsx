import { fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useDemoStore } from './demo/demoState'
import { useNotifications } from './demo/notifications'
import { clearSession, storedRefreshToken } from './services/api/client'
import { account, fakeBackend, json, problem, renderApp } from './test/fakeBackend'

function openSecurity() {
  fireEvent.click(screen.getByRole('button', { name: 'Security' }))
}

function fill(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } })
}

describe('changing your own password', () => {
  beforeEach(() => {
    clearSession()
    useNotifications.setState({ toasts: [] })
    useDemoStore.getState().startSession(account('Viewer'))
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    useDemoStore.getState().logout()
  })

  it('changes the password and keeps this tab signed in with the new session', async () => {
    const { calls } = fakeBackend({
      'POST /auth/change-password': () => json(200, { access_token: 'new-access', refresh_token: 'new-refresh-token' }),
    })
    renderApp('/settings')
    openSecurity()
    fill('Current password', 'old-password-123')
    fill('New password', 'brand-new-password-1')
    fill('Confirm password', 'brand-new-password-1')
    fireEvent.click(screen.getByRole('button', { name: 'Change password' }))

    expect(await screen.findByText('Password changed. Your other sessions were signed out.')).toBeInTheDocument()
    expect(calls.at(-1)).toMatchObject({
      method: 'POST',
      path: '/auth/change-password',
      body: { current_password: 'old-password-123', new_password: 'brand-new-password-1' },
    })
    expect(storedRefreshToken()).toBe('new-refresh-token')
    expect(screen.getByLabelText('Current password')).toHaveValue('')
  })

  it('shows a wrong current password under the field', async () => {
    fakeBackend({
      'POST /auth/change-password': () =>
        problem(400, 'urn:quantsim:problem:wrong-password', 'The current password is incorrect.'),
    })
    renderApp('/settings')
    openSecurity()
    fill('Current password', 'not-it-at-all')
    fill('New password', 'brand-new-password-1')
    fill('Confirm password', 'brand-new-password-1')
    fireEvent.click(screen.getByRole('button', { name: 'Change password' }))

    expect(await screen.findByText('The current password is incorrect.')).toBeInTheDocument()
  })

  it('checks the new password pair before sending anything', async () => {
    const { calls } = fakeBackend({})
    renderApp('/settings')
    openSecurity()
    fill('Current password', 'old-password-123')
    fill('New password', 'brand-new-password-1')
    fill('Confirm password', 'something-else-12')
    fireEvent.click(screen.getByRole('button', { name: 'Change password' }))

    expect(await screen.findByText('Passwords do not match')).toBeInTheDocument()
    await waitFor(() => expect(calls.filter((c) => c.path === '/auth/change-password')).toHaveLength(0))
  })
})
