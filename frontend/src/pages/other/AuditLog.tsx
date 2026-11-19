import { useEffect, useMemo, useState } from 'react'
import Panel from '../../components/layout/Panel'
import PageHeader from '../../components/layout/PageHeader'
import DataTable, { type Column } from '../../components/tables/DataTable'
import EmptyState from '../../components/status/EmptyState'
import StatusPill from '../../components/status/StatusPill'
import { listAuditEvents } from '../../services/api/system'
import type { AuditEvent } from '../../types'
import { errorMessage } from '../auth/authShared'

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
  const [events, setEvents] = useState<AuditEvent[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    listAuditEvents()
      .then((rows) => !cancelled && setEvents(rows))
      .catch((failure: unknown) => !cancelled && setError(errorMessage(failure)))
    return () => {
      cancelled = true
    }
  }, [])

  const rows = useMemo(
    () => (severity === 'All' ? (events ?? []) : (events ?? []).filter((e) => e.severity === severity)),
    [events, severity],
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
      {error ? (
        <p role="alert" className="text-sm text-[var(--color-risk-severe)]">
          {error}
        </p>
      ) : events === null ? (
        <p className="text-sm text-[var(--color-text-muted)]">Loading the audit log…</p>
      ) : rows.length === 0 ? (
        <EmptyState title="No events" description={severity === 'All' ? 'Nothing has been recorded yet.' : `No ${severity.toLowerCase()} events.`} />
      ) : (
        <Panel bodyClassName="p-0">
          <DataTable columns={columns} rows={rows} rowKey={(r) => r.id} />
        </Panel>
      )}
    </div>
  )
}
