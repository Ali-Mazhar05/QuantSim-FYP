import Panel from '../../components/layout/Panel'
import PageHeader from '../../components/layout/PageHeader'
import { ROLE_DESCRIPTIONS, can, type Capability } from '../../demo/permissions'
import type { Role } from '../../types'

const ROLES: Role[] = ['Viewer', 'Analyst', 'Quant', 'Admin']
const CAPABILITIES: Capability[] = [
  'view_dashboards',
  'view_reports',
  'view_alerts',
  'run_stress_test',
  'run_tda',
  'compute_metrics',
  'configure_dashboards',
  'create_alerts',
  'create_strategies',
  'calibrate_models',
  'launch_simulations',
  'create_portfolios',
  'manage_models',
  'manage_users',
  'manage_roles',
  'manage_instruments',
  'configure_system',
]

export default function Roles() {
  return (
    <div className="qs-fade-in flex flex-col gap-6">
      <PageHeader title="Roles" description="Capability model governing what each role can see and do." />

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {ROLES.map((r) => (
          <Panel key={r} title={r}>
            <p className="text-xs text-[var(--color-text-secondary)]">{ROLE_DESCRIPTIONS[r]}</p>
          </Panel>
        ))}
      </div>

      <Panel title="Capability Matrix" bodyClassName="overflow-x-auto p-0">
        <table className="w-full min-w-[640px] border-collapse text-left text-sm">
          <thead>
            <tr className="border-b border-[var(--color-border)]">
              <th className="px-3 py-2 text-xs font-semibold uppercase tracking-wide text-[var(--color-text-muted)]">Capability</th>
              {ROLES.map((r) => (
                <th key={r} className="px-3 py-2 text-center text-xs font-semibold uppercase tracking-wide text-[var(--color-text-muted)]">
                  {r}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {CAPABILITIES.map((c) => (
              <tr key={c} className="border-b border-[var(--color-border)]/60 last:border-0">
                <td className="px-3 py-2 text-[var(--color-text-secondary)]">{c.replace(/_/g, ' ')}</td>
                {ROLES.map((r) => (
                  <td key={r} className="px-3 py-2 text-center">
                    {can(r, c) ? <span className="text-[var(--color-risk-low)]">●</span> : <span className="text-[var(--color-border-strong)]">—</span>}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
    </div>
  )
}
