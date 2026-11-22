// Every page the app's router (src/App.tsx) exposes, with the heading it must show.
// Keep this list in step with App.tsx: a route added there without an entry here is a
// page the DEV smoke run does not cover.

export interface PageRoute {
  /** The URL path opened, with any :id filled in from the prototype data. */
  path: string
  /** The page's main heading (its <h1>), matched in full. */
  heading: string | RegExp
}

/** Sign-in, sign-up and the emailed-link pages, opened while signed out. */
export const PUBLIC_ROUTES: PageRoute[] = [
  { path: '/login', heading: 'QuantSim' },
  { path: '/signup', heading: 'Create account' },
  { path: '/check-email', heading: 'Check your email' },
  { path: '/forgot-password', heading: 'Forgot password' },
  // Opened without the emailed token, both pages explain that the link is not valid
  { path: '/verify-email', heading: 'Link not valid' },
  { path: '/set-password', heading: 'Link not valid' },
]

/** The pages behind sign-in, in navigation order. */
export const APP_ROUTES: PageRoute[] = [
  { path: '/dashboard', heading: /^Good (morning|afternoon|evening), (Viewer|Analyst|Quant|Admin)$/ },

  { path: '/market/environments', heading: 'Market Environments' },
  { path: '/market/environments/new', heading: 'Create Market Environment' },
  { path: '/market/data', heading: 'Market Data' },
  { path: '/market/instruments', heading: 'Instruments' },
  { path: '/market/replay', heading: 'Replay' },

  { path: '/simulation/runs', heading: 'Simulations' },
  { path: '/simulation/configure', heading: 'Simulation Configuration' },
  { path: '/simulation/run/1042', heading: 'Simulation #1042' },
  { path: '/simulation/results/1042', heading: 'Simulation #1042' },
  { path: '/simulation/calibrations', heading: 'Calibrations' },
  { path: '/simulation/models', heading: 'Models' },

  { path: '/trading/strategies', heading: 'Strategies' },
  { path: '/trading/strategies/new', heading: 'New Strategy' },
  // The prototype's strategy id names no real strategy: the page says so (a real one opens
  // as "Configure — <name>", which trading-flow.spec.ts covers)
  { path: '/trading/strategies/strat-momentum-1', heading: 'Strategy not found' },
  { path: '/trading/portfolios', heading: 'Portfolios' },
  { path: '/trading/portfolios/new', heading: 'Create Portfolio' },
  // Without a portfolio id the page offers the run picker under the prototype's heading
  { path: '/trading/replay/1042', heading: 'Trade Replay — Simulation #1042' },

  { path: '/risk/overview', heading: 'Risk Analysis' },
  { path: '/risk/stress-testing', heading: 'Stress Testing' },
  { path: '/risk/tda-analysis', heading: 'Topological Market Structure Analysis' },
  { path: '/risk/explanations', heading: 'Why is risk elevated?' },
  { path: '/risk/composite', heading: 'QuantSim Risk Hub' },
  { path: '/risk/attribution', heading: 'Attribution' },

  { path: '/ml/models', heading: 'ML Models' },
  { path: '/ml/predictions', heading: 'Machine Learning Intelligence' },
  { path: '/ml/features', heading: 'Features' },
  { path: '/ml/news-extraction', heading: 'Financial News Extraction' },

  { path: '/alerts', heading: 'Alert Hub' },
  { path: '/reports', heading: 'Reports' },
  { path: '/audit-log', heading: 'Audit Log' },
  { path: '/settings', heading: 'Settings' },
  { path: '/architecture', heading: 'System Architecture' },

  { path: '/admin/users', heading: 'Users' },
  { path: '/admin/roles', heading: 'Roles' },
  { path: '/admin/system', heading: 'System' },
]
