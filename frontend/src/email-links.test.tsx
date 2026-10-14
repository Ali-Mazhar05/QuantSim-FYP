import { fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useDemoStore } from './demo/demoState'
import { clearSession } from './services/api/client'
import { fakeBackend, json, problem, renderApp } from './test/fakeBackend'

const INVALID = () => problem(400, 'urn:quantsim:problem:invalid-link', 'This link is invalid or has expired.')

/** Open an emailed link: the address bar carries the fragment, the router the path. */
function openLink(path: string, fragment: string) {
  window.history.replaceState(null, '', `${path}#${fragment}`)
  return renderApp(path)
}

describe('the emailed-link pages', () => {
  beforeEach(() => {
    clearSession()
    useDemoStore.getState().logout()
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    window.history.replaceState(null, '', '/')
  })

  it('verifies the email, clears the token from the address bar and offers sign in', async () => {
    const { calls } = fakeBackend({
      'POST /auth/verify-email': () => json(200, { status: 'verified', approval_required: false }),
    })
    openLink('/verify-email', 'token=abc123')
    expect(await screen.findByRole('heading', { name: 'Email verified' })).toBeInTheDocument()
    expect(window.location.hash).toBe('')
    expect(window.location.href).not.toContain('abc123')
    expect(calls).toHaveLength(1)
    expect(calls[0]).toMatchObject({ path: '/auth/verify-email', body: { token: 'abc123' }, authorization: null })
    expect(screen.queryByText('An admin must approve your account before you can sign in.')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(screen.getByTestId('location')).toHaveTextContent('/login')
  })

  it('says an admin must approve when approval is required', async () => {
    fakeBackend({ 'POST /auth/verify-email': () => json(200, { status: 'verified', approval_required: true }) })
    openLink('/verify-email', 'token=abc123')
    expect(await screen.findByRole('heading', { name: 'Email verified' })).toBeInTheDocument()
    expect(screen.getByText('An admin must approve your account before you can sign in.')).toBeInTheDocument()
  })

  it('shows the invalid-link screen and sends a new link', async () => {
    const { calls } = fakeBackend({
      'POST /auth/verify-email': INVALID,
      'POST /auth/resend-verification': () => json(202, { message: 'sent' }),
    })
    openLink('/verify-email', 'token=used')
    expect(await screen.findByText('This link is invalid or has expired.')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'sara@example.com' } })
    fireEvent.click(screen.getByRole('button', { name: 'Send a new link' }))
    expect(await screen.findByText('If an account uses that email, we have sent a link.')).toBeInTheDocument()
    expect(calls.at(-1)).toMatchObject({ path: '/auth/resend-verification', body: { email: 'sara@example.com' } })
  })

  it('treats a link without a token as invalid and sends nothing', () => {
    const { fetch } = fakeBackend({})
    renderApp('/verify-email')
    expect(screen.getByText('This link is invalid or has expired.')).toBeInTheDocument()
    expect(fetch).not.toHaveBeenCalled()
  })

  it('gives the same forgot-password answer for any address', async () => {
    fakeBackend({ 'POST /auth/forgot-password': () => json(202, { message: 'sent' }) })
    for (const email of ['sara@example.com', 'nobody@example.com']) {
      const view = renderApp('/forgot-password')
      fireEvent.change(screen.getByLabelText('Email'), { target: { value: email } })
      fireEvent.click(screen.getByRole('button', { name: 'Send reset link' }))
      expect(await screen.findByText('If an account uses that email, we have sent a link.')).toBeInTheDocument()
      expect(screen.getByRole('link', { name: 'Back to sign in' })).toBeInTheDocument()
      view.unmount()
    }
  })

  it('titles the page by purpose and clears the token', () => {
    fakeBackend({})
    const view = openLink('/set-password', 'token=t1&purpose=invite')
    expect(screen.getByRole('heading', { name: 'Set your password' })).toBeInTheDocument()
    expect(window.location.hash).toBe('')
    view.unmount()
    openLink('/set-password', 'token=t2&purpose=reset')
    expect(screen.getByRole('heading', { name: 'Change your password' })).toBeInTheDocument()
  })

  it('checks the password pair before sending anything', () => {
    const { fetch } = fakeBackend({})
    openLink('/set-password', 'token=t1&purpose=reset')
    fireEvent.change(screen.getByLabelText('New password'), { target: { value: 'short' } })
    fireEvent.change(screen.getByLabelText('Confirm password'), { target: { value: 'short' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save password' }))
    expect(screen.getByText('Use 12 to 1024 characters.')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText(/^New password/), { target: { value: 'a long enough password' } })
    fireEvent.change(screen.getByLabelText('Confirm password'), { target: { value: 'another long password' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save password' }))
    expect(screen.getByText('Passwords do not match')).toBeInTheDocument()
    expect(fetch).not.toHaveBeenCalled()
  })

  it('saves the password and offers sign in', async () => {
    const { calls } = fakeBackend({ 'POST /auth/reset-password': () => json(200, { status: 'password_set' }) })
    openLink('/set-password', 'token=t1&purpose=reset')
    fireEvent.change(screen.getByLabelText('New password'), { target: { value: 'a long enough password' } })
    fireEvent.change(screen.getByLabelText('Confirm password'), { target: { value: 'a long enough password' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save password' }))
    expect(await screen.findByRole('heading', { name: 'Password saved' })).toBeInTheDocument()
    expect(calls[0].body).toEqual({ token: 't1', password: 'a long enough password' })
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/login'))
  })

  it('shows the invalid-link screen when the platform refuses the token', async () => {
    fakeBackend({ 'POST /auth/reset-password': INVALID })
    openLink('/set-password', 'token=old&purpose=reset')
    fireEvent.change(screen.getByLabelText('New password'), { target: { value: 'a long enough password' } })
    fireEvent.change(screen.getByLabelText('Confirm password'), { target: { value: 'a long enough password' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save password' }))
    expect(await screen.findByText('This link is invalid or has expired.')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Send a new link' }))
    expect(screen.getByTestId('location')).toHaveTextContent('/forgot-password')
  })
})
