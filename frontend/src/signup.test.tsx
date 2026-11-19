import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useDemoStore } from './demo/demoState'
import { clearSession } from './services/api/client'
import { account, fakeBackend, json, problem, renderApp } from './test/fakeBackend'

const PASSWORD = 'a long enough password'

function fill({
  username = 'sara.k',
  email = 'sara@example.com',
  password = PASSWORD,
  confirm = PASSWORD,
}: Partial<Record<'username' | 'email' | 'password' | 'confirm', string>> = {}) {
  fireEvent.change(screen.getByLabelText('Username'), { target: { value: username } })
  fireEvent.change(screen.getByLabelText('Email'), { target: { value: email } })
  fireEvent.change(screen.getByLabelText('Password'), { target: { value: password } })
  fireEvent.change(screen.getByLabelText('Confirm password'), { target: { value: confirm } })
}

const submit = () => fireEvent.click(screen.getByRole('button', { name: 'Create account' }))

describe('the sign-up page', () => {
  beforeEach(() => {
    clearSession()
    useDemoStore.getState().logout()
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('offers exactly Viewer, Analyst and Quant, with Quant chosen', () => {
    renderApp('/signup')
    const group = screen.getByRole('radiogroup', { name: 'Account type' })
    const types = within(group).getAllByRole('radio')
    expect(types.map((t) => t.textContent)).toEqual([
      'ViewerView dashboards, reports & alerts',
      'AnalystRun stress tests & TDA analysis',
      'QuantLaunch simulations & build portfolios',
    ])
    expect(within(group).getByRole('radio', { name: /^Quant/ })).toHaveAttribute('aria-checked', 'true')
    expect(screen.getByText('Analyst and Quant accounts are activated after an admin approves them.')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Sign in' })).toHaveAttribute('href', '/login')
  })

  it('creates the account and shows the check-email screen with the address', async () => {
    const { calls } = fakeBackend({ 'POST /auth/signup': () => json(202, { message: 'Check your email' }) })
    renderApp('/signup')
    fill({ username: 'Sara.K' })
    fireEvent.click(screen.getByRole('radio', { name: /^Analyst/ }))
    submit()
    expect(await screen.findByRole('heading', { name: 'Check your email' })).toBeInTheDocument()
    expect(screen.getByTestId('location')).toHaveTextContent('/check-email')
    expect(screen.getByText('sara@example.com')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Send the link again' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Back to sign in' })).toBeInTheDocument()
    expect(calls).toHaveLength(1)
    expect(calls[0].body).toEqual({
      username: 'sara.k',
      email: 'sara@example.com',
      password: PASSWORD,
      account_type: 'analyst',
    })
    expect(calls[0].authorization).toBeNull()
  })

  it('sends nothing when the passwords do not match', () => {
    const { fetch } = fakeBackend({})
    renderApp('/signup')
    fill({ confirm: 'a different password' })
    submit()
    expect(screen.getByText('Passwords do not match')).toBeInTheDocument()
    expect(fetch).not.toHaveBeenCalled()
  })

  it('sends nothing for a bad username, email or short password', () => {
    const { fetch } = fakeBackend({})
    renderApp('/signup')
    fill({ username: 'a b', email: 'no-at-sign', password: 'short', confirm: 'short' })
    submit()
    expect(screen.getByText('Use 3-40 characters: letters, digits, dot, underscore or hyphen.')).toBeInTheDocument()
    expect(screen.getByText('Enter a valid email address.')).toBeInTheDocument()
    expect(screen.getByText('Use 12 to 1024 characters.')).toBeInTheDocument()
    expect(fetch).not.toHaveBeenCalled()
  })

  it('shows a taken username under Username and keeps the typed values', async () => {
    fakeBackend({
      'POST /auth/signup': () => problem(409, 'urn:quantsim:problem:conflict', 'That username is already taken.'),
    })
    renderApp('/signup')
    fill()
    submit()
    expect(await screen.findByText('That username is already taken.')).toBeInTheDocument()
    expect(screen.getByLabelText(/^Username/)).toHaveValue('sara.k')
    expect(screen.getByLabelText('Email')).toHaveValue('sara@example.com')
    expect(screen.getByTestId('location')).toHaveTextContent('/signup')
  })

  it('shows the platform field errors', async () => {
    fakeBackend({
      'POST /auth/signup': () =>
        json(422, {
          type: 'about:blank',
          status: 422,
          detail: 'One or more fields are missing or invalid.',
          errors: [{ location: ['body', 'email'], message: 'value is not a valid email address', type: 'value_error' }],
        }),
    })
    renderApp('/signup')
    fill()
    submit()
    expect(await screen.findByText('value is not a valid email address')).toBeInTheDocument()
  })

  it('says when sign-up is closed', async () => {
    fakeBackend({ 'POST /auth/signup': () => problem(404, 'about:blank', 'Not Found') })
    renderApp('/signup')
    fill()
    submit()
    expect(await screen.findByText('Sign-up is closed on this environment')).toBeInTheDocument()
  })

  it('says how long to wait when sign-ups are limited', async () => {
    fakeBackend({
      'POST /auth/signup': () =>
        problem(429, 'urn:quantsim:problem:rate-limited', 'Too many requests.', { retry_after_seconds: 1800 }),
    })
    renderApp('/signup')
    fill()
    submit()
    expect(await screen.findByText('Too many attempts, try again in 30 minutes')).toBeInTheDocument()
  })

  it('sends a signed-in visitor to the dashboard', async () => {
    useDemoStore.getState().startSession(account('Viewer'))
    renderApp('/signup')
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/dashboard'))
  })
})
