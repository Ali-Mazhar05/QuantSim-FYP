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
