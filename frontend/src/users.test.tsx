import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useDemoStore } from './demo/demoState'
import { useNotifications } from './demo/notifications'
import Users from './pages/administration/Users'
import { clearSession } from './services/api/client'
import { account, fakeBackend, json, problem, renderApp } from './test/fakeBackend'

function apiUser(id: string, name: string, role: string, status: string) {
  return {
    id,
    username: name.toLowerCase().replace(' ', '.'),
    email: `${id}@example.com`,
    display_name: name,
    role,
    status,
    is_active: status !== 'disabled',
    created_at: '2026-10-01T10:00:00Z',
    last_login_at: null,
    deactivated_at: null,
    email_verified_at: status === 'invited' ? null : '2026-10-01T10:00:00Z',
    approved_at: status === 'pending' ? null : '2026-10-01T10:00:00Z',
  }
}

const USERS = [
  apiUser('u1', 'Ali Mazhar', 'admin', 'active'),
  apiUser('u2', 'Sara Khan', 'quant', 'pending'),
  apiUser('u3', 'Omar Ali', 'analyst', 'pending'),
  apiUser('u4', 'Vera Lee', 'viewer', 'active'),
]

function row(name: string) {
  return screen.getByText(name).closest('tr') as HTMLElement
}

describe('the Users page', () => {
  beforeEach(() => {
    clearSession()
    useDemoStore.getState().logout()
    useNotifications.setState({ toasts: [] })
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('gives an admin role selects and updates the row from the platform answer', async () => {
    const { calls } = fakeBackend({
      'GET /users': () => json(200, { items: USERS, total: USERS.length }),
      'PUT /users/u4/role': () => json(200, apiUser('u4', 'Vera Lee', 'analyst', 'active')),
    })
    useDemoStore.getState().startSession(account('Admin'))
    renderApp('/admin/users')
    await screen.findByText('Vera Lee')
    const select = within(row('Vera Lee')).getByRole('combobox', { name: 'Role of Vera Lee' })
    expect(select).toHaveValue('Viewer')
    fireEvent.change(select, { target: { value: 'Analyst' } })
    await waitFor(() => expect(within(row('Vera Lee')).getByRole('combobox')).toHaveValue('Analyst'))
    expect(calls.at(-1)).toMatchObject({ method: 'PUT', path: '/users/u4/role', body: { role: 'analyst' } })
    expect(await screen.findByText('Vera Lee is now Analyst')).toBeInTheDocument()
  })

  it('confirms before demoting an admin and keeps the old role when the platform refuses', async () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
    fakeBackend({
      'GET /users': () => json(200, { items: USERS, total: USERS.length }),
      'PUT /users/u1/role': () =>
        problem(409, 'urn:quantsim:problem:conflict', 'The last active administrator cannot be deactivated or demoted.'),
    })
    useDemoStore.getState().startSession(account('Admin'))
    renderApp('/admin/users')
    await screen.findByText('Ali Mazhar')
    const select = within(row('Ali Mazhar')).getByRole('combobox')
    fireEvent.change(select, { target: { value: 'Quant' } })
    expect(confirm).toHaveBeenCalledOnce()
    expect(
      await screen.findByText('The last active administrator cannot be deactivated or demoted.'),
    ).toBeInTheDocument()
    expect(within(row('Ali Mazhar')).getByRole('combobox')).toHaveValue('Admin')
  })

  it('sends nothing when the admin demotion is not confirmed', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(false)
    const { calls } = fakeBackend({ 'GET /users': () => json(200, { items: USERS, total: USERS.length }) })
    useDemoStore.getState().startSession(account('Admin'))
    renderApp('/admin/users')
    await screen.findByText('Ali Mazhar')
    fireEvent.change(within(row('Ali Mazhar')).getByRole('combobox'), { target: { value: 'Viewer' } })
    expect(calls.filter((c) => c.method === 'PUT')).toHaveLength(0)
    expect(within(row('Ali Mazhar')).getByRole('combobox')).toHaveValue('Admin')
  })

  it('shows pending rows with Approve and Reject and the awaiting count', async () => {
    const { calls } = fakeBackend({
      'GET /users': () => json(200, { items: USERS, total: USERS.length }),
      'POST /users/u2/approve': () => json(200, apiUser('u2', 'Sara Khan', 'quant', 'active')),
      'POST /users/u3/reject': () => json(200, apiUser('u3', 'Omar Ali', 'analyst', 'disabled')),
    })
    useDemoStore.getState().startSession(account('Admin'))
    renderApp('/admin/users')
    expect(await screen.findByText('2 awaiting approval')).toBeInTheDocument()
    expect(within(row('Sara Khan')).getByText('Pending')).toBeInTheDocument()
    expect(within(row('Vera Lee')).queryByRole('button', { name: 'Approve' })).not.toBeInTheDocument()

    fireEvent.click(within(row('Sara Khan')).getByRole('button', { name: 'Approve' }))
    await waitFor(() => expect(within(row('Sara Khan')).getByText('Active')).toBeInTheDocument())
    expect(screen.getByText('1 awaiting approval')).toBeInTheDocument()

    fireEvent.click(within(row('Omar Ali')).getByRole('button', { name: 'Reject' }))
    await waitFor(() => expect(within(row('Omar Ali')).getByText('Disabled')).toBeInTheDocument())
    expect(screen.queryByText(/awaiting approval/)).not.toBeInTheDocument()
    expect(calls.map((c) => `${c.method} ${c.path}`)).toContain('POST /users/u2/approve')
  })

  it('deactivates after confirming and reactivates a disabled user', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const { calls } = fakeBackend({
      'GET /users': () => json(200, { items: USERS, total: USERS.length }),
      'POST /users/u4/deactivate': () => json(200, apiUser('u4', 'Vera Lee', 'viewer', 'disabled')),
      'POST /users/u4/reactivate': () => json(200, apiUser('u4', 'Vera Lee', 'viewer', 'active')),
    })
    useDemoStore.getState().startSession(account('Admin'))
    renderApp('/admin/users')
    await screen.findByText('Vera Lee')

    fireEvent.click(within(row('Vera Lee')).getByRole('button', { name: 'Deactivate' }))
    await waitFor(() => expect(within(row('Vera Lee')).getByText('Disabled')).toBeInTheDocument())
    fireEvent.click(within(row('Vera Lee')).getByRole('button', { name: 'Reactivate' }))
    await waitFor(() => expect(within(row('Vera Lee')).getByText('Active')).toBeInTheDocument())
    expect(calls.map((c) => `${c.method} ${c.path}`)).toEqual(
      expect.arrayContaining(['POST /users/u4/deactivate', 'POST /users/u4/reactivate']),
    )
  })

  it('offers no Deactivate on your own row', async () => {
    const me = { ...apiUser('u9', 'Admin User', 'admin', 'active'), email: 'admin.user@quantsim.dev' }
    fakeBackend({ 'GET /users': () => json(200, { items: [...USERS, me], total: USERS.length + 1 }) })
    useDemoStore.getState().startSession(account('Admin'))
    renderApp('/admin/users')
    await screen.findByText('Admin User')

    expect(within(row('Admin User')).queryByRole('button', { name: 'Deactivate' })).not.toBeInTheDocument()
    expect(within(row('Vera Lee')).getByRole('button', { name: 'Deactivate' })).toBeInTheDocument()
  })

  it('invites a user without a password and adds an Invited row', async () => {
    const { calls } = fakeBackend({
      'GET /users': () => json(200, { items: USERS, total: USERS.length }),
      'POST /users': () => json(201, apiUser('u5', 'Nadia Q', 'admin', 'invited')),
      'POST /users/u5/resend-invite': () => json(202, { message: 'sent' }),
    })
    useDemoStore.getState().startSession(account('Admin'))
    renderApp('/admin/users')
    await screen.findByText('Vera Lee')
    fireEvent.click(screen.getByRole('button', { name: 'Invite User' }))
    const dialog = screen.getByRole('heading', { name: 'Invite User' }).closest('div.qs-panel') as HTMLElement
    expect(within(dialog).queryByLabelText(/password/i)).not.toBeInTheDocument()
    fireEvent.change(within(dialog).getByLabelText('Username'), { target: { value: 'nadia.q' } })
    fireEvent.change(within(dialog).getByLabelText('Email'), { target: { value: 'nadia@example.com' } })
    fireEvent.change(within(dialog).getByLabelText('Display name'), { target: { value: 'Nadia Q' } })
    fireEvent.change(within(dialog).getByLabelText('Role'), { target: { value: 'Admin' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Send invitation' }))

    await screen.findByText('Nadia Q')
    expect(within(row('Nadia Q')).getByText('Invited')).toBeInTheDocument()
    expect(calls.find((c) => c.method === 'POST' && c.path === '/users')?.body).toEqual({
      username: 'nadia.q',
      email: 'nadia@example.com',
      display_name: 'Nadia Q',
      role: 'admin',
    })

    fireEvent.click(within(row('Nadia Q')).getByRole('button', { name: 'Resend invite' }))
    await waitFor(() => expect(calls.at(-1)?.path).toBe('/users/u5/resend-invite'))
  })

  it('shows plain text and no controls to a role without user management', async () => {
    fakeBackend({ 'GET /users': () => json(200, { items: USERS, total: USERS.length }) })
    // An admin previewing as Analyst sees exactly what an Analyst sees
    useDemoStore.getState().startSession(account('Admin'))
    useDemoStore.getState().setRole('Analyst')
    render(
      <MemoryRouter>
        <Users />
      </MemoryRouter>,
    )
    await screen.findByText('Vera Lee')
    expect(screen.queryAllByRole('combobox')).toHaveLength(0)
    expect(within(row('Vera Lee')).getByText('Viewer')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Approve' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Reject' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Invite User' })).toBeDisabled()
  })
})
