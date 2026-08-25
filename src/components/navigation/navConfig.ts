import type { LucideIcon } from 'lucide-react'
import {
  Activity,
  AlertTriangle,
  Boxes,
  Cpu,
  FileBarChart,
  Fingerprint,
  Gauge,
  LayoutDashboard,
  LineChart,
  ListTree,
  Network,
  Rewind,
  Settings2,
  ShieldAlert,
  ShieldHalf,
  Sigma,
  SlidersHorizontal,
  Sparkles,
  Target,
  Users,
  Wallet,
} from 'lucide-react'

export interface NavItem {
  label: string
  path: string
  icon: LucideIcon
}

export interface NavSection {
  title: string
  items: NavItem[]
}

export const NAV_SECTIONS: NavSection[] = [
  {
    title: 'Overview',
    items: [{ label: 'Dashboard', path: '/dashboard', icon: LayoutDashboard }],
  },
  {
    title: 'Market',
    items: [
      { label: 'Market Environments', path: '/market/environments', icon: Boxes },
      { label: 'Market Data', path: '/market/data', icon: LineChart },
      { label: 'Instruments', path: '/market/instruments', icon: Target },
      { label: 'Replay', path: '/market/replay', icon: Rewind },
    ],
  },
  {
    title: 'Simulation',
    items: [
      { label: 'Simulations', path: '/simulation/runs', icon: Sigma },
      { label: 'Calibrations', path: '/simulation/calibrations', icon: SlidersHorizontal },
      { label: 'Models', path: '/simulation/models', icon: ListTree },
    ],
  },
  {
    title: 'Trading',
    items: [
      { label: 'Strategies', path: '/trading/strategies', icon: Gauge },
      { label: 'Portfolios', path: '/trading/portfolios', icon: Wallet },
      { label: 'Trade Replay', path: '/trading/replay/1042', icon: Activity },
    ],
  },
  {
    title: 'Intelligence',
    items: [
      { label: 'ML Models', path: '/ml/models', icon: Cpu },
      { label: 'Predictions', path: '/ml/predictions', icon: Sparkles },
      { label: 'Features', path: '/ml/features', icon: Fingerprint },
    ],
  },
  {
    title: 'Risk',
    items: [
      { label: 'Risk Overview', path: '/risk/overview', icon: ShieldHalf },
      { label: 'Stress Testing', path: '/risk/stress-testing', icon: ShieldAlert },
      { label: 'TDA Analysis', path: '/risk/tda-analysis', icon: Network },
      { label: 'Explainability', path: '/risk/explanations', icon: FileBarChart },
      { label: 'Attribution', path: '/risk/attribution', icon: Sigma },
    ],
  },
  {
    title: 'Monitoring',
    items: [
      { label: 'Alerts', path: '/alerts', icon: AlertTriangle },
      { label: 'Reports', path: '/reports', icon: FileBarChart },
      { label: 'Audit Log', path: '/audit-log', icon: ListTree },
    ],
  },
  {
    title: 'Administration',
    items: [
      { label: 'Users', path: '/admin/users', icon: Users },
      { label: 'Roles', path: '/admin/roles', icon: ShieldHalf },
      { label: 'System', path: '/admin/system', icon: Settings2 },
    ],
  },
]
