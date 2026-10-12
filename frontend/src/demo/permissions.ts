// Capability model referenced by the QuantSim role documentation, mocked
// here purely to drive which POC actions are enabled/visible per role.

import type { Role } from '../types'

export type Capability =
  | 'view_dashboards'
  | 'view_reports'
  | 'view_alerts'
  | 'run_stress_test'
  | 'run_tda'
  | 'compute_metrics'
  | 'configure_dashboards'
  | 'create_alerts'
  | 'create_strategies'
  | 'calibrate_models'
  | 'launch_simulations'
  | 'create_portfolios'
  | 'manage_models'
  | 'manage_users'
  | 'manage_roles'
  | 'manage_instruments'
  | 'configure_system'

const CAPABILITIES: Record<Role, Capability[]> = {
  Viewer: ['view_dashboards', 'view_reports', 'view_alerts'],
  Analyst: [
    'view_dashboards',
    'view_reports',
    'view_alerts',
    'run_stress_test',
    'run_tda',
    'compute_metrics',
    'configure_dashboards',
    'create_alerts',
  ],
  Quant: [
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
  ],
  Admin: [
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
  ],
}

export function can(role: Role, capability: Capability): boolean {
  return CAPABILITIES[role].includes(capability)
}

export const ROLE_DESCRIPTIONS: Record<Role, string> = {
  Viewer: 'View dashboards, reports and alerts.',
  Analyst: 'Run stress tests and TDA, compute metrics, configure dashboards and alerts.',
  Quant: 'Create strategies, calibrate models, launch simulations and create portfolios.',
  Admin: 'Manage users, roles, instruments and system configuration.',
}

// Role order for "preview as an equal or lower role" (the backend's ROLE_RANK)
export const ROLE_RANK: Record<Role, number> = { Viewer: 0, Analyst: 1, Quant: 2, Admin: 3 }

export function rolesUpTo(role: Role): Role[] {
  return (Object.keys(ROLE_RANK) as Role[]).filter((r) => ROLE_RANK[r] <= ROLE_RANK[role])
}

// The capability each page needs, in matching order (first match wins). A role without it
// does not see the page in the navigation and is sent to the dashboard if it opens the URL;
// the backend refuses the same actions on every request, so this is convenience, not
// protection. Pages not listed (and unknown URLs) are open to every signed-in role.
const PAGE_CAPABILITY: [RegExp, Capability][] = [
  [/^\/market\/environments\/new$/, 'launch_simulations'],
  [/^\/simulation\/(configure|run\/[^/]+)$/, 'launch_simulations'],
  [/^\/simulation\/(calibrations|models)$/, 'calibrate_models'],
  [/^\/trading\/strategies\/[^/]+$/, 'create_strategies'],
  [/^\/trading\/portfolios\/new$/, 'create_portfolios'],
  [/^\/risk\/stress-testing$/, 'run_stress_test'],
  [/^\/risk\/tda-analysis$/, 'run_tda'],
  [/^\/risk\/attribution$/, 'compute_metrics'],
  [/^\/ml\/features$/, 'compute_metrics'],
  [/^\/ml\/(models|news-extraction)$/, 'manage_models'],
  [/^\/audit-log$/, 'configure_system'],
  [/^\/admin\/users$/, 'manage_users'],
  [/^\/admin\/roles$/, 'manage_roles'],
  [/^\/admin\/system$/, 'configure_system'],
]

export function pageCapability(pathname: string): Capability | null {
  return PAGE_CAPABILITY.find(([pattern]) => pattern.test(pathname))?.[1] ?? null
}

export function canOpen(role: Role, pathname: string): boolean {
  const needed = pageCapability(pathname)
  return needed === null || can(role, needed)
}
