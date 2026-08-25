import { useMemo, useState } from 'react'
import Panel from '../../components/layout/Panel'
import PageHeader from '../../components/layout/PageHeader'
import DataTable, { type Column } from '../../components/tables/DataTable'
import StatusPill from '../../components/status/StatusPill'
import { AUDIT_EVENTS } from '../../services/mock/data'
import type { AuditEvent } from '../../types'

const columns: Column<AuditEvent>[] = [
  { key: 'time', header: 'Time', render: (r) => <span className="mono">{r.timestamp}</span> },
  { key: 'user', header: 'User', render: (r) => r.user },
  { key: 'service', header: 'Service', render: (r) => r.service },
  { key: 'action', header: 'Action', render: (r) => <span className="text-[var(--color-text-primary)]">{r.action}</span> },
  {
    key: 'severity',
    header: 'Severity',
    render: (r) => (
      <StatusPill tone={r.severity === 'Critical' ? 'danger' : r.severity === 'Warning' ? 'warning' : 'neutral'}>{r.severity}</StatusPill>
    ),
  },
]

export default function AuditLog() {
  const [severity, setSeverity] = useState<string>('All')
  const rows = useMemo(
    () => (severity === 'All' ? AUDIT_EVENTS : AUDIT_EVENTS.filter((e) => e.severity === severity)),
    [severity],
  )

  return (
    <div className="qs-fade-in flex flex-col gap-6">
      <PageHeader title="Audit Log" description="Chronological record of actions across the QuantSim platform." />
      <div className="flex flex-wrap gap-2">
        {['All', 'Info', 'Warning', 'Critical'].map((s) => (
          <button
            key={s}
            onClick={() => setSeverity(s)}
            className={`rounded border px-2.5 py-1 text-xs font-medium ${
              severity === s
                ? 'border-[var(--color-accent-strong)] bg-[var(--color-accent)]/12 text-[var(--color-accent-strong)]'
                : 'border-[var(--color-border-strong)] text-[var(--color-text-secondary)]'
            }`}
          >
            {s}
          </button>
        ))}
      </div>
      <Panel bodyClassName="p-0">
        <DataTable columns={columns} rows={rows} rowKey={(r) => r.id} />
      </Panel>
    </div>
  )
}
