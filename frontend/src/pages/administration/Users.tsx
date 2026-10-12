import { Plus } from 'lucide-react'
import { useEffect, useState } from 'react'
import Button from '../../components/forms/Button'
import Panel from '../../components/layout/Panel'
import PageHeader from '../../components/layout/PageHeader'
import DataTable, { type Column } from '../../components/tables/DataTable'
import StatusPill from '../../components/status/StatusPill'
import { useDemoStore } from '../../demo/demoState'
import { useDemoModeModal, useNotifications } from '../../demo/notifications'
import { useCan } from '../../demo/useCan'
import { listUsers } from '../../services/api/platform'
import { USERS } from '../../services/mock/data'
import type { UserAccount } from '../../types'

const columns: Column<UserAccount>[] = [
  { key: 'name', header: 'Name', render: (r) => <span className="font-medium text-[var(--color-text-primary)]">{r.name}</span> },
  { key: 'email', header: 'Email', render: (r) => <span className="mono text-xs">{r.email}</span> },
  { key: 'role', header: 'Role', render: (r) => r.role },
  {
    key: 'status',
    header: 'Status',
    render: (r) => <StatusPill tone={r.status === 'Active' ? 'success' : r.status === 'Invited' ? 'info' : 'neutral'} dot>{r.status}</StatusPill>,
  },
  { key: 'lastActive', header: 'Last Active', align: 'right', render: (r) => <span className="mono text-xs">{r.lastActive}</span> },
]

export default function Users() {
  const show = useDemoModeModal((s) => s.show)
  const live = useDemoStore((s) => s.mode === 'live')
  const canManage = useCan('manage_users')
  const notify = useNotifications((s) => s.push)
  // Real accounts when signed in against the backend; the POC's sample rows in demo mode
  const [rows, setRows] = useState<UserAccount[]>(live ? [] : USERS)

  useEffect(() => {
    if (!live) return
    let cancelled = false
    listUsers()
      .then((users) => !cancelled && setRows(users))
      .catch(() => !cancelled && notify('Could not load users', 'warning'))
    return () => {
      cancelled = true
    }
  }, [live, notify])

  return (
    <div className="qs-fade-in flex flex-col gap-6">
      <PageHeader
        title="Users"
        description="Accounts provisioned for the Research Environment."
        action={
          <Button icon={Plus} onClick={show} disabled={!canManage}>
            Invite User
          </Button>
        }
      />
      <Panel bodyClassName="p-0">
        <DataTable columns={columns} rows={rows} rowKey={(r) => r.id} />
      </Panel>
    </div>
  )
}
