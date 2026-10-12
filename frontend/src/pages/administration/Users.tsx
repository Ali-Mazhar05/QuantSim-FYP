import { Plus } from 'lucide-react'
import { useEffect, useState } from 'react'
import Button from '../../components/forms/Button'
import Modal from '../../components/modals/Modal'
import Panel from '../../components/layout/Panel'
import PageHeader from '../../components/layout/PageHeader'
import DataTable, { type Column } from '../../components/tables/DataTable'
import StatusPill from '../../components/status/StatusPill'
import { useNotifications } from '../../demo/notifications'
import { useCan } from '../../demo/useCan'
import { ApiError } from '../../services/api/client'
import { approveUser, changeRole, inviteUser, listUsers, rejectUser, resendInvite } from '../../services/api/platform'
import type { Role, UserAccount } from '../../types'
import AuthField from '../auth/AuthField'
import { emailProblem, errorMessage, usernameProblem } from '../auth/authShared'

const ROLES: Role[] = ['Viewer', 'Analyst', 'Quant', 'Admin']

const STATUS_TONES: Record<UserAccount['status'], 'success' | 'info' | 'warning' | 'neutral'> = {
  Active: 'success',
  Invited: 'info',
  Pending: 'warning',
  Disabled: 'neutral',
}

// The POC select
const SELECT_CLASS =
  'rounded border border-[var(--color-border-strong)] bg-[var(--color-bg-2)] px-3 py-1.5 text-sm text-[var(--color-text-primary)] focus:border-[var(--color-accent-strong)] focus:outline-none'

export default function Users() {
  const canManage = useCan('manage_users')
  const canManageRoles = useCan('manage_roles')
  const notify = useNotifications((s) => s.push)
  const [rows, setRows] = useState<UserAccount[]>([])
  const [busy, setBusy] = useState<string | null>(null)
  const [inviteOpen, setInviteOpen] = useState(false)

  useEffect(() => {
    let cancelled = false
    listUsers()
      .then((users) => !cancelled && setRows(users))
      .catch(() => !cancelled && notify('Could not load users', 'warning'))
    return () => {
      cancelled = true
    }
  }, [notify])

  // Rows change only from what the platform answers
  const replaceRow = (user: UserAccount) => setRows((current) => current.map((r) => (r.id === user.id ? user : r)))

  const act = async (row: UserAccount, action: () => Promise<UserAccount | void>, success: string) => {
    setBusy(row.id)
    try {
      const user = await action()
      if (user) replaceRow(user)
      notify(success, 'success')
    } catch (failure) {
      notify(errorMessage(failure), 'warning')
    } finally {
      setBusy(null)
    }
  }

  const onRoleChange = (row: UserAccount, role: Role) => {
    if (role === row.role) return
    if (
      row.role === 'Admin' &&
      !window.confirm(`Change ${row.name} from Admin to ${role}? They will no longer manage users and roles.`)
    ) {
      return
    }
    void act(row, () => changeRole(row.id, role), `${row.name} is now ${role}`)
  }

  const pendingCount = rows.filter((r) => r.status === 'Pending').length

  const columns: Column<UserAccount>[] = [
    { key: 'name', header: 'Name', render: (r) => <span className="font-medium text-[var(--color-text-primary)]">{r.name}</span> },
    { key: 'email', header: 'Email', render: (r) => <span className="mono text-xs">{r.email}</span> },
    {
      key: 'role',
      header: 'Role',
      render: (r) =>
        canManageRoles ? (
          <select
            aria-label={`Role of ${r.name}`}
            value={r.role}
            disabled={busy === r.id}
            onChange={(e) => onRoleChange(r, e.target.value as Role)}
            className={SELECT_CLASS}
          >
            {ROLES.map((role) => (
              <option key={role} value={role}>
                {role}
              </option>
            ))}
          </select>
        ) : (
          r.role
        ),
    },
    {
      key: 'status',
      header: 'Status',
      render: (r) => (
        <StatusPill tone={STATUS_TONES[r.status]} dot>
          {r.status}
        </StatusPill>
      ),
    },
    { key: 'lastActive', header: 'Last Active', align: 'right', render: (r) => <span className="mono text-xs">{r.lastActive}</span> },
  ]

  if (canManage) {
    columns.push({
      key: 'actions',
      header: 'Actions',
      align: 'right',
      render: (r) => (
        <div className="flex justify-end gap-2">
          {r.status === 'Pending' && (
            <>
              <Button
                size="sm"
                variant="secondary"
                disabled={busy === r.id}
                onClick={() => act(r, () => approveUser(r.id), `${r.name} is approved`)}
              >
                Approve
              </Button>
              <Button
                size="sm"
                variant="ghost"
                disabled={busy === r.id}
                onClick={() => act(r, () => rejectUser(r.id), `${r.name} is rejected`)}
              >
                Reject
              </Button>
            </>
          )}
          {r.status === 'Invited' && (
            <Button
              size="sm"
              variant="ghost"
              disabled={busy === r.id}
              onClick={() => act(r, () => resendInvite(r.id), `Invitation sent again to ${r.email}`)}
            >
              Resend invite
            </Button>
          )}
        </div>
      ),
    })
  }

  return (
    <div className="qs-fade-in flex flex-col gap-6">
      <PageHeader
        title="Users"
        description="Accounts provisioned for the Research Environment."
        action={
          <>
            {pendingCount > 0 && <StatusPill tone="warning">{pendingCount} awaiting approval</StatusPill>}
            <Button icon={Plus} onClick={() => setInviteOpen(true)} disabled={!canManage}>
              Invite User
            </Button>
          </>
        }
      />
      <Panel bodyClassName="p-0">
        <DataTable columns={columns} rows={rows} rowKey={(r) => r.id} />
      </Panel>
      {canManage && (
        <InviteUserModal
          open={inviteOpen}
          onClose={() => setInviteOpen(false)}
          onInvited={(user) => {
            setRows((current) => [...current, user])
            setInviteOpen(false)
            notify(`Invitation sent to ${user.email}`, 'success')
          }}
        />
      )}
    </div>
  )
}

type InviteField = 'username' | 'email' | 'display_name' | 'role'

function InviteUserModal({
  open,
  onClose,
  onInvited,
}: {
  open: boolean
  onClose: () => void
  onInvited: (user: UserAccount) => void
}) {
  const [username, setUsername] = useState('')
  const [email, setEmail] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [role, setRole] = useState<Role>('Viewer')
  const [errors, setErrors] = useState<Partial<Record<InviteField, string>>>({})
  const [formError, setFormError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const reset = () => {
    setUsername('')
    setEmail('')
    setDisplayName('')
    setRole('Viewer')
    setErrors({})
    setFormError(null)
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setFormError(null)
    const found: Partial<Record<InviteField, string | undefined>> = {
      username: usernameProblem(username) ?? undefined,
      email: emailProblem(email) ?? undefined,
      display_name: displayName.trim() ? undefined : 'Enter a display name.',
    }
    const problems = Object.fromEntries(Object.entries(found).filter(([, v]) => v)) as Partial<Record<InviteField, string>>
    setErrors(problems)
    if (Object.keys(problems).length > 0) return
    setSubmitting(true)
    try {
      const user = await inviteUser({
        username: username.trim().toLowerCase(),
        email: email.trim(),
        displayName: displayName.trim(),
        role,
      })
      reset()
      onInvited(user)
    } catch (failure) {
      if (failure instanceof ApiError && failure.status === 422 && Object.keys(failure.fieldErrors).length > 0) {
        setErrors(failure.fieldErrors as Partial<Record<InviteField, string>>)
      } else {
        setFormError(errorMessage(failure))
      }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Modal open={open} onClose={onClose} title="Invite User" width="sm">
      <form onSubmit={handleSubmit} noValidate>
        <p className="mb-4 text-xs leading-relaxed text-[var(--color-text-secondary)]">
          The user gets an email with a link to set their own password.
        </p>
        {formError && (
          <div
            role="alert"
            className="mb-4 rounded border border-[var(--color-risk-elevated)]/70 bg-[var(--color-risk-elevated)]/10 px-3 py-2 text-xs text-[var(--color-risk-elevated)]"
          >
            {formError}
          </div>
        )}
        <AuthField label="Username" value={username} onChange={setUsername} error={errors.username} />
        <AuthField label="Email" type="email" value={email} onChange={setEmail} error={errors.email} />
        <AuthField label="Display name" value={displayName} onChange={setDisplayName} error={errors.display_name} />
        <label className="mb-5 block">
          <span className="mb-1 block text-xs font-medium text-[var(--color-text-secondary)]">Role</span>
          <select value={role} onChange={(e) => setRole(e.target.value as Role)} className={`${SELECT_CLASS} w-full`}>
            {ROLES.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
          {errors.role && <span className="mt-1 block text-[11px] text-[var(--color-risk-severe)]">{errors.role}</span>}
        </label>
        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" loading={submitting}>
            Send invitation
          </Button>
        </div>
      </form>
    </Modal>
  )
}
