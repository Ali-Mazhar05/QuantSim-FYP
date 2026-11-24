import { useEffect, useState } from 'react'
import Panel from '../../components/layout/Panel'
import PageHeader from '../../components/layout/PageHeader'
import StatusPill from '../../components/status/StatusPill'
import { type ServiceHealth, serviceHealth } from '../../services/api/system'

// The prototype's service cards. A card with a service name is checked live through the
// gateway; the others are modules not deployed yet and say so instead of claiming health.
// The gateway is up when any service answers through it.
const SERVICES: { name: string; check: string | 'gateway' | null }[] = [
  { name: 'API Gateway', check: 'gateway' },
  { name: 'Market Data', check: 'market' },
  { name: 'Simulation', check: 'simulation' },
  { name: 'Trading', check: null },
  { name: 'ML', check: null },
  { name: 'Risk / TDA', check: null },
  { name: 'XAI', check: null },
  { name: 'Event Backbone', check: null },
]

const SITE_ENVIRONMENTS: Record<string, string> = { develop: 'DEV', test: 'TEST', acceptance: 'ACC' }

function siteEnvironment(): string {
  const host = window.location.hostname
  if (host === 'localhost' || host === '127.0.0.1') return 'Local'
  return SITE_ENVIRONMENTS[host.split('.')[0]] ?? 'PROD'
}

type Checks = Record<'platform' | 'market' | 'simulation', ServiceHealth>

function cardStatus(check: string | null, checks: Checks | null): { label: string; tone: 'success' | 'danger' | 'neutral' } {
  if (check === null) return { label: 'Not deployed', tone: 'neutral' }
  if (checks === null) return { label: 'Checking…', tone: 'neutral' }
  const up = check === 'gateway' ? checks.platform.up || checks.market.up : checks[check as keyof Checks].up
  return up ? { label: 'Operational', tone: 'success' } : { label: 'Unavailable', tone: 'danger' }
}

export default function System() {
  const [checks, setChecks] = useState<Checks | null>(null)

  useEffect(() => {
    let cancelled = false
    Promise.all([serviceHealth('platform'), serviceHealth('market'), serviceHealth('simulation')]).then(
      ([platform, market, simulation]) => !cancelled && setChecks({ platform, market, simulation }),
    )
    return () => {
      cancelled = true
    }
  }, [])

  const version = checks?.platform.version ?? checks?.market.version ?? '—'

  return (
    <div className="qs-fade-in flex flex-col gap-6">
      <PageHeader title="System" description="Platform configuration and service health overview." />
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {SERVICES.map((s) => {
          const status = cardStatus(s.check, checks)
          return (
            <div key={s.name} className="qs-panel flex items-center justify-between rounded p-4">
              <span className="text-sm font-medium text-[var(--color-text-primary)]">{s.name}</span>
              <StatusPill tone={status.tone} dot>
                {status.label}
              </StatusPill>
            </div>
          )
        })}
      </div>
      <Panel title="Environment">
        <dl className="grid grid-cols-2 gap-4 text-sm sm:grid-cols-4">
          <div>
            <dt className="text-xs text-[var(--color-text-muted)]">Environment</dt>
            <dd className="mt-0.5 text-[var(--color-text-primary)]">{siteEnvironment()}</dd>
          </div>
          <div>
            <dt className="text-xs text-[var(--color-text-muted)]">Version</dt>
            <dd className="mono mt-0.5 text-[var(--color-text-primary)]">{version}</dd>
          </div>
          <div>
            <dt className="text-xs text-[var(--color-text-muted)]">Region</dt>
            <dd className="mt-0.5 text-[var(--color-text-primary)]">Self-hosted</dd>
          </div>
          <div>
            <dt className="text-xs text-[var(--color-text-muted)]">Mode</dt>
            <dd className="mt-0.5 text-[var(--color-text-primary)]">Live</dd>
          </div>
        </dl>
      </Panel>
    </div>
  )
}
