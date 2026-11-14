// Calls behind the prototype's Audit Log and System pages: the audit feed every service
// serves in the same row shape (merged here by time), and each service's health check.

import type { AuditEvent } from '../../types'
import { apiBaseUrl, apiRequest } from './client'
import { listUsers } from './platform'

interface ApiAuditEvent {
  id: string
  occurred_at: string
  actor_id: string | null
  actor: string | null
  service: string
  action: string
  severity: 'info' | 'warning' | 'critical'
  detail: string
}

const SEVERITY_NAMES: Record<ApiAuditEvent['severity'], AuditEvent['severity']> = {
  info: 'Info',
  warning: 'Warning',
  critical: 'Critical',
}

/** The services that serve an audit feed, in the order their rows break ties. */
const AUDITED_SERVICES = ['platform', 'market'] as const

function timestamp(iso: string): string {
  const date = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, '0')
  return (
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ` +
    `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
  )
}

/** The latest audit events of every service, newest first, in the prototype's row shape.
 * A user is shown by name; the system (scheduler, worker) is shown as "System". */
export async function listAuditEvents(limit = 200): Promise<AuditEvent[]> {
  const [feeds, users] = await Promise.all([
    Promise.all(
      AUDITED_SERVICES.map((service) => apiRequest<ApiAuditEvent[]>(`/api/${service}/audit?limit=${limit}`)),
    ),
    listUsers(),
  ])
  const names = new Map(users.map((u) => [u.id, u.name]))
  return feeds
    .flat()
    .sort((a, b) => Date.parse(b.occurred_at) - Date.parse(a.occurred_at))
    .slice(0, limit)
    .map((e) => ({
      id: e.id,
      timestamp: timestamp(e.occurred_at),
      user: (e.actor_id && names.get(e.actor_id)) || e.actor || (e.actor_id ? 'Unknown user' : 'System'),
      service: e.service,
      action: e.action,
      severity: SEVERITY_NAMES[e.severity],
      detail: e.detail,
    }))
}

export interface ServiceHealth {
  /** Answered its health check. */
  up: boolean
  version: string | null
}

/** A service's public health check through the gateway; never throws. */
export async function serviceHealth(service: string, timeoutMs = 4000): Promise<ServiceHealth> {
  const controller = new AbortController()
  const timer = window.setTimeout(() => controller.abort(), timeoutMs)
  try {
    const response = await fetch(`${apiBaseUrl()}/api/${service}/health`, { signal: controller.signal })
    if (!response.ok) return { up: false, version: null }
    const body: { version?: unknown } = await response.json()
    return { up: true, version: typeof body.version === 'string' ? body.version : null }
  } catch {
    return { up: false, version: null }
  } finally {
    window.clearTimeout(timer)
  }
}
