// The prototype pages wired to the Iteration 1 APIs: Market Environments, Create Market
// Environment, the top bar, Replay, Audit Log and System. The layout is the prototype's;
// these tests check the data behind it and what is sent.

import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useDemoStore } from './demo/demoState'
import { useNotifications } from './demo/notifications'
import { clearSession } from './services/api/client'
import { account, fakeBackend, json, problem, renderApp } from './test/fakeBackend'

const AAPL = {
  id: 'id-aapl',
  symbol: 'AAPL',
  name: 'Apple Inc.',
  sector: 'Technology',
  price: '186.88000000',
  change_pct: '1.20',
  status: 'active',
  exchange: 'XNAS',
  asset_class: 'equity',
}
const MSFT = { ...AAPL, id: 'id-msft', symbol: 'MSFT', name: 'Microsoft Corp.' }
const SPY = { ...AAPL, id: 'id-spy', symbol: 'SPY', name: 'SPDR S&P 500', asset_class: 'etf' }

function environment(id: string, name: string, overrides: Record<string, unknown> = {}) {
  return {
    id,
    name,
    type: 'historical_replay',
    universe: 'US Technology Basket',
    instrument_ids: ['id-aapl', 'id-msft'],
    symbols: ['AAPL', 'MSFT'],
    start_date: '2025-01-01',
    end_date: '2026-06-30',
    frequency: 'daily',
    status: 'ready',
    created_by: 'u1',
    created_at: '2026-11-01T10:00:00Z',
    ...overrides,
  }
}

function candles(count: number) {
  return {
    interval: 'daily',
    items: Array.from({ length: count }, (_, i) => {
      const day = new Date(Date.UTC(2025, 0, 2) + i * 86_400_000).toISOString().slice(0, 10)
      const close = String(100 + i)
      return { session_date: day, period_start: day, open: close, high: close, low: close, close, volume: '10', adj_close: close, sessions: 1 }
    }),
  }
}

beforeEach(() => {
  clearSession()
  useDemoStore.getState().logout()
  useDemoStore.getState().resetDemo()
  useNotifications.setState({ toasts: [] })
})
afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('Market Environments', () => {
  it('lists the environments from the API in the prototype columns', async () => {
    fakeBackend({
      'GET /api/market/environments': () =>
        json(200, [
          environment('e2', 'Rates Shock', { type: 'synthetic', status: 'draft', frequency: 'hourly' }),
          environment('e1', 'US Tech Replay'),
        ]),
    })
    useDemoStore.getState().startSession(account('Quant'))
    renderApp('/market/environments')

    const row = (await screen.findAllByText('Rates Shock')).find((el) => el.closest('tr'))!.closest('tr') as HTMLElement
    expect(within(row).getByText('Synthetic Market')).toBeInTheDocument()
    expect(within(row).getByText('Hourly')).toBeInTheDocument()
    expect(within(row).getByText('Draft')).toBeInTheDocument()
    expect(within(row).getByText('2025-01-01 → 2026-06-30')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /New Environment/ })).toBeEnabled()
  })

  it('shows an empty state instead of mock rows when there are none', async () => {
    fakeBackend({ 'GET /api/market/environments': () => json(200, []) })
    useDemoStore.getState().startSession(account('Quant'))
    renderApp('/market/environments')
    expect(await screen.findByText('No environments yet')).toBeInTheDocument()
  })

  it('disables New Environment when the backend did not grant create_market_environments', async () => {
    fakeBackend({ 'GET /api/market/environments': () => json(200, []) })
    // A quant role whose /auth/me capability list lacks the capability: the server decides
    const limited = { ...account('Quant'), capabilities: account('Quant').capabilities.filter((c) => c !== 'create_market_environments') }
    useDemoStore.getState().startSession(limited)
    renderApp('/market/environments')
    await screen.findByText('No environments yet')
    expect(screen.getByRole('button', { name: /New Environment/ })).toBeDisabled()
  })
})

describe('Create Market Environment', () => {
  it('saves the prototype window and the selected real instruments, then makes it active', async () => {
    let created: Record<string, unknown> | undefined
    const { calls } = fakeBackend({
      'GET /api/market/instruments': () => json(200, [AAPL, MSFT, SPY]),
      'GET /api/market/instruments/id-aapl/candles': () => json(200, candles(30)),
      'GET /api/market/environments': () => json(200, created ? [environment('new', 'US Technology Basket', { type: 'synthetic' })] : []),
      'POST /api/market/environments': (body) => {
        created = body
        return json(201, environment('new', 'US Technology Basket', { type: 'synthetic' }))
      },
    })
    useDemoStore.getState().startSession(account('Quant'))
    renderApp('/market/environments/new')

    // The prototype's starting selection, kept to the instruments that exist
    await screen.findByRole('button', { name: 'SPY' })
    await waitFor(() => expect(calls.some((c) => c.path === '/api/market/instruments/id-aapl/candles')).toBe(true))
    const preview = calls.find((c) => c.path.endsWith('/candles'))!
    expect(preview).toBeDefined()
    expect(screen.getByText('AAPL — reference series')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'SPY' }))
    fireEvent.click(screen.getByRole('button', { name: /Continue to Simulation/ }))

    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/simulation/configure'))
    expect(created).toEqual({
      name: 'US Technology Basket',
      type: 'synthetic',
      universe: 'US Technology Basket',
      instrument_ids: ['id-aapl', 'id-msft', 'id-spy'],
      start_date: '2025-01-01',
      end_date: '2026-06-30',
      frequency: 'daily',
    })
    expect(useDemoStore.getState().activeEnvironmentId).toBe('new')
    expect(useDemoStore.getState().flowStep).toBe('MARKET_SELECTED')
  })

  it('stays on the page and says why when the API refuses the environment', async () => {
    fakeBackend({
      'GET /api/market/instruments': () => json(200, [AAPL]),
      'GET /api/market/instruments/id-aapl/candles': () => json(200, candles(5)),
      'GET /api/market/environments': () => json(200, []),
      'POST /api/market/environments': () =>
        problem(422, 'urn:quantsim:problem:invalid-instruments', 'Every instrument must exist and be active.'),
    })
    useDemoStore.getState().startSession(account('Quant'))
    renderApp('/market/environments/new')
    await screen.findByRole('button', { name: 'AAPL' })
    fireEvent.click(screen.getByRole('button', { name: /Continue to Simulation/ }))
    await waitFor(() =>
      expect(useNotifications.getState().toasts.map((t) => t.title)).toContain('Every instrument must exist and be active.'),
    )
    expect(screen.getByTestId('location')).toHaveTextContent('/market/environments/new')
    expect(useDemoStore.getState().activeEnvironmentId).toBeNull()
  })
})

describe('the top bar and Replay', () => {
  it('names the active environment and replays its window with real sessions', async () => {
    const { calls } = fakeBackend({
      'GET /api/market/environments': () => json(200, [environment('e2', 'Newest Env'), environment('e1', 'Chosen Env')]),
      'GET /api/market/instruments/id-aapl/candles': () => json(200, candles(100)),
    })
    useDemoStore.getState().startSession(account('Viewer'))
    useDemoStore.getState().setActiveEnvironment('e1')
    renderApp('/market/replay')

    expect(await screen.findByText('Chosen Env — Historical Replay')).toBeInTheDocument()
    expect(screen.getByText('2025-01-01 → 2026-06-30 · Daily')).toBeInTheDocument()
    expect(await screen.findByText('Session 42 / 100')).toBeInTheDocument()
    await waitFor(() => expect(screen.getAllByText('Chosen Env').length).toBeGreaterThan(0))
    const request = calls.find((c) => c.path.endsWith('/candles'))
    expect(request).toBeDefined()
  })

  it('falls back to the newest environment and says when there is none', async () => {
    fakeBackend({ 'GET /api/market/environments': () => json(200, []) })
    useDemoStore.getState().startSession(account('Viewer'))
    renderApp('/market/replay')
    expect(await screen.findByText('No environment yet')).toBeInTheDocument()
    expect(screen.getByText('No environment')).toBeInTheDocument()
  })
})

function feedEvent(id: string, at: string, overrides: Record<string, unknown>) {
  return { id, occurred_at: at, actor_id: null, actor: null, service: 'Market Data', action: 'x', severity: 'info', detail: '', ...overrides }
}

describe('Audit Log', () => {
  it('merges every service feed newest first, names users and filters by severity', async () => {
    fakeBackend({
      'GET /audit': () =>
        json(200, [
          feedEvent('platform:audit:2:0', '2026-11-13T10:00:00Z', {
            service: 'Platform',
            action: 'Role of vera changed',
            severity: 'warning',
            actor_id: 'u1',
            actor: 'admin',
          }),
        ]),
      'GET /api/market/audit': () =>
        json(200, [
          feedEvent('market:run:r1:finished', '2026-11-13T11:00:00Z', {
            action: 'Ingestion run succeeded',
            severity: 'warning',
            detail: '1 instruments: 40 bars received, 37 passed, 0 corrected, 3 rejected, 37 new, 0 revised.',
          }),
          feedEvent('market:audit:5', '2026-11-13T09:00:00Z', { action: 'Instrument ZZ added', actor_id: 'u1' }),
          feedEvent('market:run:r2:finished', '2026-11-13T08:00:00Z', { action: 'Ingestion run failed', severity: 'critical' }),
        ]),
      'GET /users': () =>
        json(200, {
          items: [
            {
              id: 'u1',
              username: 'ali',
              email: 'ali@quantsim.dev',
              display_name: 'Ali Mazhar',
              role: 'admin',
              status: 'active',
              is_active: true,
              last_login_at: null,
            },
          ],
          total: 1,
        }),
      'GET /api/market/environments': () => json(200, []),
    })
    useDemoStore.getState().startSession(account('Admin'))
    renderApp('/audit-log')

    await screen.findByText('Ingestion run succeeded')
    const actions = screen.getAllByRole('row').slice(1).map((r) => within(r).getAllByRole('cell')[3].textContent)
    expect(actions).toEqual(['Ingestion run succeeded', 'Role of vera changed', 'Instrument ZZ added', 'Ingestion run failed'])
    const rows = screen.getAllByRole('row').slice(1)
    expect(within(rows[0]).getByText('System')).toBeInTheDocument()
    expect(within(rows[0]).getByText('Market Data')).toBeInTheDocument()
    expect(within(rows[1]).getByText('Ali Mazhar')).toBeInTheDocument()
    expect(within(rows[2]).getByText('Ali Mazhar')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Critical' }))
    expect(screen.getAllByRole('row').slice(1)).toHaveLength(1)
    expect(screen.getByText('Ingestion run failed')).toBeInTheDocument()
  })

  it('shows the error instead of mock rows when a feed cannot be read', async () => {
    fakeBackend({
      'GET /audit': () => json(200, []),
      'GET /api/market/audit': () => problem(403, 'about:blank', 'Not allowed'),
      'GET /users': () => json(200, { items: [], total: 0 }),
      'GET /api/market/environments': () => json(200, []),
    })
    useDemoStore.getState().startSession(account('Admin'))
    renderApp('/audit-log')
    expect(await screen.findByRole('alert')).toHaveTextContent('Not allowed')
  })
})

describe('System', () => {
  it('shows live health for the deployed services and Not deployed for the rest', async () => {
    fakeBackend({
      'GET /health': () => json(200, { status: 'ok', service: 'platform', version: '0.3.0', content_hash: 'abc' }),
      'GET /api/market/health': () => json(503, { status: 'down' }),
      'GET /api/market/environments': () => json(200, []),
    })
    useDemoStore.getState().startSession(account('Admin'))
    renderApp('/admin/system')

    // The sidebar also says "Market Data" and "Simulation"; a card is a .qs-panel
    const card = (name: string) =>
      screen
        .getAllByText(name)
        .map((el) => el.closest('.qs-panel'))
        .find((el): el is HTMLElement => el instanceof HTMLElement && el.querySelector('[class*="rounded"]') !== null)!
    await waitFor(() => expect(within(card('API Gateway')).getByText('Operational')).toBeInTheDocument())
    expect(within(card('Market Data')).getByText('Unavailable')).toBeInTheDocument()
    expect(within(card('Simulation')).getByText('Not deployed')).toBeInTheDocument()
    expect(within(card('Event Backbone')).getByText('Not deployed')).toBeInTheDocument()
    expect(screen.getByText('0.3.0')).toBeInTheDocument()
    expect(screen.getByText('Live')).toBeInTheDocument()
  })
})
